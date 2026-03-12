package main

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	conformance "conformance-sendspin-go/internal/conformance"
	"github.com/Sendspin/sendspin-go/pkg/protocol"
	"github.com/gorilla/websocket"
)

const audioChunkMessageType = 4

type args struct {
	ClientName       string
	ClientID         string
	Summary          string
	Ready            string
	Registry         string
	ScenarioID       string
	InitiatorRole    string
	PreferredCodec   string
	ServerName       string
	ServerID         string
	TimeoutSeconds   float64
	MetadataTitle    string
	MetadataArtist   string
	MetadataAlbum    string
	MetadataAlbumArt string
	MetadataURL      string
	MetadataYear     int
	MetadataTrack    int
	MetadataRepeat   string
	MetadataShuffle  string
	MetadataProgress int
	MetadataDuration int
	MetadataSpeed    int
}

func main() {
	parsed := parseArgs()
	os.Exit(run(parsed))
}

func parseArgs() args {
	var parsed args
	flag.StringVar(&parsed.ClientName, "client-name", "", "")
	flag.StringVar(&parsed.ClientID, "client-id", "", "")
	flag.StringVar(&parsed.Summary, "summary", "", "")
	flag.StringVar(&parsed.Ready, "ready", "", "")
	flag.StringVar(&parsed.Registry, "registry", "", "")
	flag.StringVar(&parsed.ScenarioID, "scenario-id", "client-initiated-pcm", "")
	flag.StringVar(&parsed.InitiatorRole, "initiator-role", "client", "")
	flag.StringVar(&parsed.PreferredCodec, "preferred-codec", "pcm", "")
	flag.StringVar(&parsed.ServerName, "server-name", "Sendspin Conformance Server", "")
	flag.StringVar(&parsed.ServerID, "server-id", "conformance-server", "")
	flag.Float64Var(&parsed.TimeoutSeconds, "timeout-seconds", 30.0, "")
	flag.StringVar(&parsed.MetadataTitle, "metadata-title", "Almost Silent", "")
	flag.StringVar(&parsed.MetadataArtist, "metadata-artist", "Sendspin Conformance", "")
	flag.StringVar(&parsed.MetadataAlbumArt, "metadata-album-artist", "Sendspin", "")
	flag.StringVar(&parsed.MetadataAlbum, "metadata-album", "Protocol Fixtures", "")
	flag.StringVar(&parsed.MetadataURL, "metadata-artwork-url", "https://example.invalid/almost-silent.jpg", "")
	flag.IntVar(&parsed.MetadataYear, "metadata-year", 2026, "")
	flag.IntVar(&parsed.MetadataTrack, "metadata-track", 1, "")
	flag.StringVar(&parsed.MetadataRepeat, "metadata-repeat", "all", "")
	flag.StringVar(&parsed.MetadataShuffle, "metadata-shuffle", "false", "")
	flag.IntVar(&parsed.MetadataProgress, "metadata-track-progress", 12000, "")
	flag.IntVar(&parsed.MetadataDuration, "metadata-track-duration", 180000, "")
	flag.IntVar(&parsed.MetadataSpeed, "metadata-playback-speed", 1000, "")
	flag.Parse()
	return parsed
}

func run(parsed args) int {
	if err := conformance.WriteJSON(parsed.Ready, map[string]any{
		"status":         "ready",
		"scenario_id":    parsed.ScenarioID,
		"initiator_role": parsed.InitiatorRole,
	}); err != nil {
		log.Printf("failed to write ready file: %v", err)
	}

	if parsed.InitiatorRole != "client" {
		return exitWithSummary(parsed, errorSummary(parsed, "sendspin-go client only supports client-initiated scenarios"))
	}
	if !supportsScenario(parsed.ScenarioID) {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("sendspin-go client does not support %s", parsed.ScenarioID)))
	}

	serverURL, err := conformance.WaitForEndpoint(
		parsed.Registry,
		parsed.ServerName,
		time.Duration(parsed.TimeoutSeconds*float64(time.Second)),
	)
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, err.Error()))
	}

	conn, _, err := websocket.DefaultDialer.Dial(serverURL, nil)
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to connect: %v", err)))
	}
	defer conn.Close()

	if err := writeEnvelope(conn, "client/hello", buildClientHello(parsed)); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, err.Error()))
	}

	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	messageType, helloBytes, err := conn.ReadMessage()
	conn.SetReadDeadline(time.Time{})
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to read server/hello: %v", err)))
	}
	if messageType != websocket.TextMessage {
		return exitWithSummary(parsed, errorSummary(parsed, "expected text server/hello"))
	}

	rawPeerHello := decodeRawJSON(helloBytes)
	var envelope conformance.Envelope
	if err := json.Unmarshal(helloBytes, &envelope); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/hello: %v", err)))
	}
	if envelope.Type != "server/hello" {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("expected server/hello, got %s", envelope.Type)))
	}

	var serverHello protocol.ServerHello
	if err := json.Unmarshal(envelope.Payload, &serverHello); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/hello payload: %v", err)))
	}

	if isPlayerScenario(parsed.ScenarioID) {
		if err := writeEnvelope(conn, "client/state", protocol.ClientStateMessage{
			Player: &protocol.PlayerState{
				State:  "synchronized",
				Volume: 100,
				Muted:  false,
			},
		}); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to send client/state: %v", err)))
		}
		if err := writeEnvelope(conn, "client/time", protocol.ClientTime{
			ClientTransmitted: conformance.CurrentMicros(),
		}); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to send client/time: %v", err)))
		}
	}

	streamStart := (*protocol.StreamStartPlayer)(nil)
	pcmHasher := conformance.NewFloatPcmHasher()
	encodedHasher := sha256.New()
	audioChunkCount := 0
	metadataUpdateCount := 0
	var receivedMetadata any
	timeoutAt := time.Now().Add(time.Duration(parsed.TimeoutSeconds * float64(time.Second)))

	for {
		if err := conn.SetReadDeadline(timeoutAt); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to set read deadline: %v", err)))
		}
		messageType, payload, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				break
			}
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("timed out waiting for server disconnect in %s", parsed.ScenarioID)))
			}
			if websocket.IsUnexpectedCloseError(err) {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("websocket read failed: %v", err)))
			}
			break
		}

		switch messageType {
		case websocket.TextMessage:
			var message conformance.Envelope
			if err := json.Unmarshal(payload, &message); err != nil {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid JSON message: %v", err)))
			}
			switch message.Type {
			case "stream/start":
				var start protocol.StreamStart
				if err := json.Unmarshal(message.Payload, &start); err != nil {
					return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid stream/start: %v", err)))
				}
				streamStart = start.Player
			case "server/state":
				var state protocol.ServerStateMessage
				if err := json.Unmarshal(message.Payload, &state); err != nil {
					return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/state: %v", err)))
				}
				if state.Metadata != nil {
					metadataUpdateCount++
					receivedMetadata = normalizeMetadata(state.Metadata)
				}
			case "group/update", "server/time", "stream/end":
			default:
				log.Printf("Ignoring unsupported message type %s", message.Type)
			}
		case websocket.BinaryMessage:
			if !isPlayerScenario(parsed.ScenarioID) {
				continue
			}
			if len(payload) < 9 {
				return exitWithSummary(parsed, errorSummary(parsed, "audio chunk was shorter than protocol header"))
			}
			if payload[0] != audioChunkMessageType {
				continue
			}
			if streamStart == nil {
				return exitWithSummary(parsed, errorSummary(parsed, "received audio before stream/start"))
			}
			audioBytes := payload[9:]
			_, _ = encodedHasher.Write(audioBytes)
			if streamStart.Codec != "pcm" {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("unsupported audio codec %q", streamStart.Codec)))
			}
			if err := pcmHasher.UpdateFromPCMBytes(audioBytes, streamStart.BitDepth); err != nil {
				return exitWithSummary(parsed, errorSummary(parsed, err.Error()))
			}
			audioChunkCount++
		}
	}

	summary := map[string]any{
		"status":          "ok",
		"implementation":  "sendspin-go",
		"role":            "client",
		"scenario_id":     parsed.ScenarioID,
		"initiator_role":  parsed.InitiatorRole,
		"preferred_codec": parsed.PreferredCodec,
		"client_name":     parsed.ClientName,
		"client_id":       parsed.ClientID,
		"peer_hello":      rawPeerHello,
		"server": map[string]any{
			"server_id":         serverHello.ServerID,
			"name":              serverHello.Name,
			"version":           serverHello.Version,
			"active_roles":      serverHello.ActiveRoles,
			"connection_reason": serverHello.ConnectionReason,
		},
	}

	if isPlayerScenario(parsed.ScenarioID) {
		if audioChunkCount == 0 {
			return exitWithSummary(parsed, errorSummary(parsed, "client received zero audio chunks"))
		}
		summary["stream"] = normalizeStreamStart(streamStart)
		summary["audio"] = map[string]any{
			"audio_chunk_count":      audioChunkCount,
			"received_encoded_sha256": conformance.HexLower(encodedHasher.Sum(nil)),
			"received_pcm_sha256":     pcmHasher.HexDigest(),
			"received_sample_count":   pcmHasher.SampleCount,
		}
	} else {
		if metadataUpdateCount == 0 {
			return exitWithSummary(parsed, errorSummary(parsed, "client received zero metadata updates"))
		}
		summary["metadata"] = map[string]any{
			"update_count": metadataUpdateCount,
			"received":     receivedMetadata,
		}
	}

	return exitWithSummary(parsed, summary)
}

func supportsScenario(scenarioID string) bool {
	return isPlayerScenario(scenarioID) || scenarioID == "client-initiated-metadata"
}

func isPlayerScenario(scenarioID string) bool {
	return scenarioID == "client-initiated-pcm"
}

func buildClientHello(parsed args) protocol.ClientHello {
	hello := protocol.ClientHello{
		ClientID: parsed.ClientID,
		Name:     parsed.ClientName,
		Version:  1,
		DeviceInfo: &protocol.DeviceInfo{
			ProductName:     "sendspin-go Conformance Client",
			Manufacturer:    "Sendspin Conformance",
			SoftwareVersion: "0.1.0",
		},
	}

	if isPlayerScenario(parsed.ScenarioID) {
		hello.SupportedRoles = []string{"player@v1"}
		hello.PlayerV1Support = &protocol.PlayerV1Support{
			SupportedFormats: []protocol.AudioFormat{
				{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 24},
				{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 16},
			},
			BufferCapacity:    1_000_000,
			SupportedCommands: []string{"volume", "mute"},
		}
		return hello
	}

	hello.SupportedRoles = []string{"metadata@v1"}
	return hello
}

func normalizeMetadata(metadata *protocol.MetadataState) map[string]any {
	result := map[string]any{
		"title":        derefString(metadata.Title),
		"artist":       derefString(metadata.Artist),
		"album_artist": derefString(metadata.AlbumArtist),
		"album":        derefString(metadata.Album),
		"artwork_url":  derefString(metadata.ArtworkURL),
		"year":         derefInt(metadata.Year),
		"track":        derefInt(metadata.Track),
		"repeat":       derefString(metadata.Repeat),
		"shuffle":      derefBool(metadata.Shuffle),
	}
	if metadata.Progress != nil {
		result["progress"] = map[string]any{
			"track_progress": metadata.Progress.TrackProgress,
			"track_duration": metadata.Progress.TrackDuration,
			"playback_speed": metadata.Progress.PlaybackSpeed,
		}
	}
	return result
}

func normalizeStreamStart(start *protocol.StreamStartPlayer) any {
	if start == nil {
		return nil
	}
	return map[string]any{
		"codec":        start.Codec,
		"sample_rate":  start.SampleRate,
		"channels":     start.Channels,
		"bit_depth":    start.BitDepth,
		"codec_header": start.CodecHeader,
	}
}

func writeEnvelope(conn *websocket.Conn, messageType string, payload any) error {
	body, err := json.Marshal(map[string]any{
		"type":    messageType,
		"payload": payload,
	})
	if err != nil {
		return err
	}
	return conn.WriteMessage(websocket.TextMessage, body)
}

func decodeRawJSON(raw []byte) any {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil
	}
	return value
}

func errorSummary(parsed args, reason string) map[string]any {
	return map[string]any{
		"status":          "error",
		"reason":          reason,
		"implementation":  "sendspin-go",
		"role":            "client",
		"scenario_id":     parsed.ScenarioID,
		"initiator_role":  parsed.InitiatorRole,
		"preferred_codec": parsed.PreferredCodec,
		"client_name":     parsed.ClientName,
		"client_id":       parsed.ClientID,
		"peer_hello":      nil,
	}
}

func exitWithSummary(parsed args, summary map[string]any) int {
	if err := conformance.WriteJSON(parsed.Summary, summary); err != nil {
		log.Printf("failed to write summary: %v", err)
		return 1
	}
	if err := conformance.PrintFile(parsed.Summary); err != nil {
		log.Printf("failed to print summary: %v", err)
	}
	if status, ok := summary["status"].(string); ok && status == "ok" {
		return 0
	}
	return 1
}

func derefString(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func derefInt(value *int) any {
	if value == nil {
		return nil
	}
	return *value
}

func derefBool(value *bool) any {
	if value == nil {
		return nil
	}
	return *value
}

func init() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
}
