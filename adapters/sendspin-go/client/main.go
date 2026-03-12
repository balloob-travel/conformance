package main

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	conformance "conformance-sendspin-go/internal/conformance"
	"github.com/Sendspin/sendspin-go/pkg/protocol"
	"github.com/gorilla/websocket"
)

type args struct {
	ClientName        string
	ClientID          string
	Summary           string
	Ready             string
	Registry          string
	ScenarioID        string
	InitiatorRole     string
	PreferredCodec    string
	ServerName        string
	ServerID          string
	TimeoutSeconds    float64
	Port              int
	Path              string
	MetadataTitle     string
	MetadataArtist    string
	MetadataAlbum     string
	MetadataAlbumArt  string
	MetadataURL       string
	MetadataYear      int
	MetadataTrack     int
	MetadataRepeat    string
	MetadataShuffle   string
	MetadataProgress  int
	MetadataDuration  int
	MetadataSpeed     int
	ControllerCommand string
	ArtworkFormat     string
	ArtworkWidth      int
	ArtworkHeight     int
}

type sessionResult struct {
	summary map[string]any
	err     error
}

type streamStartPayload struct {
	Player  *protocol.StreamStartPlayer `json:"player,omitempty"`
	Artwork any                         `json:"artwork,omitempty"`
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
	flag.IntVar(&parsed.Port, "port", 8928, "")
	flag.StringVar(&parsed.Path, "path", "/sendspin", "")
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
	flag.StringVar(&parsed.ControllerCommand, "controller-command", "next", "")
	flag.StringVar(&parsed.ArtworkFormat, "artwork-format", "jpeg", "")
	flag.IntVar(&parsed.ArtworkWidth, "artwork-width", 256, "")
	flag.IntVar(&parsed.ArtworkHeight, "artwork-height", 256, "")
	flag.Parse()
	return parsed
}

func run(parsed args) int {
	if !conformance.SupportsScenario(parsed.ScenarioID) {
		return exitWithSummary(
			parsed,
			errorSummary(parsed, fmt.Sprintf("sendspin-go client does not support %s", parsed.ScenarioID), nil, nil),
		)
	}

	if parsed.InitiatorRole == "client" {
		if err := conformance.WriteJSON(parsed.Ready, conformance.BuildReadyPayload(parsed.ScenarioID, parsed.InitiatorRole, "")); err != nil {
			log.Printf("failed to write ready file: %v", err)
		}

		serverURL, err := conformance.WaitForEndpoint(
			parsed.Registry,
			parsed.ServerName,
			time.Duration(parsed.TimeoutSeconds*float64(time.Second)),
		)
		if err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, err.Error(), nil, nil))
		}

		conn, _, err := websocket.DefaultDialer.Dial(serverURL, nil)
		if err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to connect: %v", err), nil, nil))
		}
		defer conn.Close()

		return runConnectedSession(parsed, conn)
	}

	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", parsed.Port))
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to bind listener: %v", err), nil, nil))
	}
	defer listener.Close()

	sessionCh := make(chan sessionResult, 1)
	upgrader := websocket.Upgrader{
		CheckOrigin: func(_ *http.Request) bool { return true },
	}
	attached := false
	mux := http.NewServeMux()
	mux.HandleFunc(parsed.Path, func(w http.ResponseWriter, r *http.Request) {
		if attached {
			http.Error(w, "busy", http.StatusConflict)
			return
		}
		attached = true
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			sessionCh <- sessionResult{err: fmt.Errorf("failed to upgrade websocket: %w", err)}
			return
		}
		go func() {
			defer conn.Close()
			code := runConnectedSession(parsed, conn)
			summary, readErr := readSummary(parsed.Summary)
			if readErr != nil {
				sessionCh <- sessionResult{err: fmt.Errorf("failed to read session summary: %w", readErr)}
				return
			}
			if code != 0 && summary == nil {
				sessionCh <- sessionResult{err: fmt.Errorf("session exited %d without summary", code)}
				return
			}
			sessionCh <- sessionResult{summary: summary}
		}()
	})

	server := &http.Server{Handler: mux}
	go func() {
		if serveErr := server.Serve(listener); serveErr != nil && serveErr != http.ErrServerClosed {
			sessionCh <- sessionResult{err: serveErr}
		}
	}()

	url := fmt.Sprintf("ws://127.0.0.1:%d%s", parsed.Port, parsed.Path)
	if err := conformance.RegisterEndpoint(parsed.Registry, parsed.ClientName, url); err != nil {
		_ = server.Close()
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to register endpoint: %v", err), nil, nil))
	}
	if err := conformance.WriteJSON(parsed.Ready, conformance.BuildReadyPayload(parsed.ScenarioID, parsed.InitiatorRole, url)); err != nil {
		log.Printf("failed to write ready file: %v", err)
	}

	select {
	case result := <-sessionCh:
		_ = server.Close()
		if result.err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, result.err.Error(), nil, nil))
		}
		if result.summary != nil {
			if status, ok := result.summary["status"].(string); ok && status == "ok" {
				return 0
			}
		}
		return 1
	case <-time.After(time.Duration(parsed.TimeoutSeconds * float64(time.Second))):
		_ = server.Close()
		return exitWithSummary(parsed, errorSummary(parsed, "timed out waiting for server connection", nil, nil))
	}
}

func runConnectedSession(parsed args, conn *websocket.Conn) int {
	if err := writeEnvelope(conn, "client/hello", buildClientHello(parsed)); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, err.Error(), nil, nil))
	}

	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	messageType, helloBytes, err := conn.ReadMessage()
	conn.SetReadDeadline(time.Time{})
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to read server/hello: %v", err), nil, nil))
	}
	if messageType != websocket.TextMessage {
		return exitWithSummary(parsed, errorSummary(parsed, "expected text server/hello", nil, nil))
	}

	rawPeerHello := decodeRawJSON(helloBytes)
	var envelope conformance.Envelope
	if err := json.Unmarshal(helloBytes, &envelope); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/hello: %v", err), rawPeerHello, nil))
	}
	if envelope.Type != "server/hello" {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("expected server/hello, got %s", envelope.Type), rawPeerHello, nil))
	}

	var serverHello protocol.ServerHello
	if err := json.Unmarshal(envelope.Payload, &serverHello); err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/hello payload: %v", err), rawPeerHello, nil))
	}

	if conformance.IsPlayerScenario(parsed.ScenarioID) {
		if err := writeEnvelope(conn, "client/state", protocol.ClientStateMessage{
			Player: &protocol.PlayerState{
				State:  "synchronized",
				Volume: 100,
				Muted:  false,
			},
		}); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to send client/state: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
		}
		if err := writeEnvelope(conn, "client/time", protocol.ClientTime{
			ClientTransmitted: conformance.CurrentMicros(),
		}); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to send client/time: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
		}
	}

	var currentPlayer *protocol.StreamStartPlayer
	var artworkStream any
	pcmHasher := conformance.NewFloatPcmHasher()
	encodedHasher := sha256.New()
	audioChunkCount := 0
	metadataUpdateCount := 0
	var receivedMetadata any
	var receivedControllerState any
	var sentControllerCommand any
	artworkHasher := sha256.New()
	artworkChannel := -1
	artworkCount := 0
	artworkByteCount := 0
	timeoutAt := time.Now().Add(time.Duration(parsed.TimeoutSeconds * float64(time.Second)))

	for {
		if err := conn.SetReadDeadline(timeoutAt); err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to set read deadline: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
		}
		messageType, payload, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				break
			}
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("timed out waiting for server disconnect in %s", parsed.ScenarioID), rawPeerHello, serverHelloPayload(&serverHello)))
			}
			if websocket.IsUnexpectedCloseError(err) {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("websocket read failed: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
			}
			break
		}

		switch messageType {
		case websocket.TextMessage:
			rawValue := decodeRawJSON(payload)
			var message conformance.Envelope
			if err := json.Unmarshal(payload, &message); err != nil {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid JSON message: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
			}
			switch message.Type {
			case "stream/start":
				var start streamStartPayload
				if err := json.Unmarshal(message.Payload, &start); err != nil {
					return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid stream/start: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
				}
				currentPlayer = start.Player
				if rawMap, ok := rawValue.(map[string]any); ok {
					if payloadMap, ok := rawMap["payload"].(map[string]any); ok {
						if artworkValue, ok := payloadMap["artwork"]; ok {
							artworkStream = artworkValue
						}
					}
				}
			case "server/state":
				var state protocol.ServerStateMessage
				if err := json.Unmarshal(message.Payload, &state); err != nil {
					return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("invalid server/state: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
				}
				if state.Metadata != nil {
					metadataUpdateCount++
					receivedMetadata = normalizeMetadata(state.Metadata)
				}
				if state.Controller != nil {
					receivedControllerState = normalizeController(state.Controller)
					if conformance.IsControllerScenario(parsed.ScenarioID) && sentControllerCommand == nil {
						if containsString(state.Controller.SupportedCommands, parsed.ControllerCommand) {
							sentControllerCommand = map[string]any{"command": parsed.ControllerCommand}
							if err := writeEnvelope(conn, "client/command", map[string]any{
								"controller": sentControllerCommand,
							}); err != nil {
								return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to send client/command: %v", err), rawPeerHello, serverHelloPayload(&serverHello)))
							}
						}
					}
				}
			case "group/update", "server/time", "stream/end":
			default:
				log.Printf("Ignoring unsupported message type %s", message.Type)
			}
		case websocket.BinaryMessage:
			if len(payload) < 9 {
				return exitWithSummary(parsed, errorSummary(parsed, "binary frame was shorter than protocol header", rawPeerHello, serverHelloPayload(&serverHello)))
			}

			messageCode := int(payload[0])
			data := payload[9:]
			if conformance.IsArtworkScenario(parsed.ScenarioID) && messageCode >= conformance.ArtworkChannel0MessageType && messageCode <= conformance.ArtworkChannel0MessageType+3 {
				artworkChannel = messageCode - conformance.ArtworkChannel0MessageType
				artworkCount++
				artworkByteCount += len(data)
				_, _ = artworkHasher.Write(data)
				continue
			}

			if !conformance.IsPlayerScenario(parsed.ScenarioID) {
				continue
			}
			if messageCode != conformance.AudioChunkMessageType {
				continue
			}
			if currentPlayer == nil {
				return exitWithSummary(parsed, errorSummary(parsed, "received audio before stream/start", rawPeerHello, serverHelloPayload(&serverHello)))
			}
			_, _ = encodedHasher.Write(data)
			if strings.EqualFold(currentPlayer.Codec, "pcm") {
				if err := pcmHasher.UpdateFromPCMBytes(data, currentPlayer.BitDepth); err != nil {
					return exitWithSummary(parsed, errorSummary(parsed, err.Error(), rawPeerHello, serverHelloPayload(&serverHello)))
				}
			} else if !strings.EqualFold(currentPlayer.Codec, "flac") {
				return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("unsupported audio codec %q", currentPlayer.Codec), rawPeerHello, serverHelloPayload(&serverHello)))
			}
			audioChunkCount++
		}
	}

	if rawPeerHello == nil {
		return exitWithSummary(parsed, errorSummary(parsed, "connection closed before handshake completed", nil, nil))
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
		"server":          serverHelloPayload(&serverHello),
	}

	switch {
	case conformance.IsPlayerScenario(parsed.ScenarioID):
		if audioChunkCount == 0 {
			return exitWithSummary(parsed, errorSummary(parsed, "client received zero audio chunks", rawPeerHello, serverHelloPayload(&serverHello)))
		}
		summary["stream"] = normalizeStreamStart(currentPlayer)
		summary["audio"] = map[string]any{
			"audio_chunk_count":       audioChunkCount,
			"received_encoded_sha256": conformance.HexLower(encodedHasher.Sum(nil)),
			"received_pcm_sha256":     pcmDigestOrNil(pcmHasher),
			"received_sample_count":   pcmHasher.SampleCount,
		}
	case conformance.IsMetadataScenario(parsed.ScenarioID):
		summary["metadata"] = map[string]any{
			"update_count": metadataUpdateCount,
			"received":     receivedMetadata,
		}
	case conformance.IsControllerScenario(parsed.ScenarioID):
		summary["controller"] = map[string]any{
			"received_state": receivedControllerState,
			"sent_command":   sentControllerCommand,
		}
	case conformance.IsArtworkScenario(parsed.ScenarioID):
		summary["stream"] = artworkStream
		summary["artwork"] = map[string]any{
			"channel":        nilIfNegative(artworkChannel),
			"received_count": artworkCount,
			"received_sha256": func() any {
				if artworkCount == 0 {
					return nil
				}
				return conformance.HexLower(artworkHasher.Sum(nil))
			}(),
			"byte_count": artworkByteCount,
		}
	}

	return exitWithSummary(parsed, summary)
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

	switch {
	case conformance.IsMetadataScenario(parsed.ScenarioID):
		hello.SupportedRoles = []string{"metadata@v1"}
	case conformance.IsControllerScenario(parsed.ScenarioID):
		hello.SupportedRoles = []string{"controller@v1"}
	case conformance.IsArtworkScenario(parsed.ScenarioID):
		hello.SupportedRoles = []string{"artwork@v1"}
		hello.ArtworkV1Support = &protocol.ArtworkV1Support{
			Channels: []protocol.ArtworkChannel{
				{
					Source:      "album",
					Format:      conformance.NormalizeArtworkFormat(parsed.ArtworkFormat),
					MediaWidth:  parsed.ArtworkWidth,
					MediaHeight: parsed.ArtworkHeight,
				},
			},
		}
	default:
		hello.SupportedRoles = []string{"player@v1"}
		hello.PlayerV1Support = &protocol.PlayerV1Support{
			SupportedFormats: playerFormats(parsed.PreferredCodec),
			BufferCapacity:   2_000_000,
			SupportedCommands: []string{
				"volume",
				"mute",
			},
		}
	}
	return hello
}

func playerFormats(preferredCodec string) []protocol.AudioFormat {
	if strings.EqualFold(preferredCodec, "pcm") {
		return []protocol.AudioFormat{
			{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 24},
			{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 16},
		}
	}
	return []protocol.AudioFormat{
		{Codec: "flac", Channels: 1, SampleRate: 8000, BitDepth: 24},
		{Codec: "flac", Channels: 1, SampleRate: 8000, BitDepth: 16},
		{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 24},
		{Codec: "pcm", Channels: 1, SampleRate: 8000, BitDepth: 16},
	}
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

func normalizeController(controller *protocol.ControllerState) map[string]any {
	return map[string]any{
		"supported_commands": controller.SupportedCommands,
		"volume":             controller.Volume,
		"muted":              controller.Muted,
	}
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

func serverHelloPayload(hello *protocol.ServerHello) any {
	if hello == nil {
		return nil
	}
	return map[string]any{
		"server_id":         hello.ServerID,
		"name":              hello.Name,
		"version":           hello.Version,
		"active_roles":      hello.ActiveRoles,
		"connection_reason": hello.ConnectionReason,
	}
}

func readSummary(path string) (map[string]any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var value map[string]any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	return value, nil
}

func pcmDigestOrNil(hasher *conformance.FloatPcmHasher) any {
	if hasher == nil || hasher.SampleCount == 0 {
		return nil
	}
	return hasher.HexDigest()
}

func nilIfNegative(value int) any {
	if value < 0 {
		return nil
	}
	return value
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if strings.EqualFold(value, target) {
			return true
		}
	}
	return false
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

func errorSummary(parsed args, reason string, peerHello any, server any) map[string]any {
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
		"peer_hello":      peerHello,
		"server":          server,
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
