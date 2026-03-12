package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	conformance "conformance-sendspin-go/internal/conformance"
	"github.com/Sendspin/sendspin-go/pkg/protocol"
	"github.com/gorilla/websocket"
)

const audioChunkMessageType = 4

type args struct {
	ClientName        string
	Summary           string
	Ready             string
	Registry          string
	Fixture           string
	ScenarioID        string
	InitiatorRole     string
	PreferredCodec    string
	TimeoutSeconds    float64
	Port              int
	Host              string
	ServerID          string
	ServerName        string
	ClipSeconds       float64
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
}

type sessionResult struct {
	summary map[string]any
	err     error
}

func main() {
	parsed := parseArgs()
	os.Exit(run(parsed))
}

func parseArgs() args {
	var parsed args
	flag.StringVar(&parsed.ClientName, "client-name", "", "")
	flag.StringVar(&parsed.Summary, "summary", "", "")
	flag.StringVar(&parsed.Ready, "ready", "", "")
	flag.StringVar(&parsed.Registry, "registry", "", "")
	flag.StringVar(&parsed.Fixture, "fixture", "", "")
	flag.StringVar(&parsed.ScenarioID, "scenario-id", "client-initiated-pcm", "")
	flag.StringVar(&parsed.InitiatorRole, "initiator-role", "client", "")
	flag.StringVar(&parsed.PreferredCodec, "preferred-codec", "pcm", "")
	flag.Float64Var(&parsed.TimeoutSeconds, "timeout-seconds", 30.0, "")
	flag.IntVar(&parsed.Port, "port", 8927, "")
	flag.StringVar(&parsed.Host, "host", "127.0.0.1", "")
	flag.StringVar(&parsed.ServerID, "server-id", "conformance-server", "")
	flag.StringVar(&parsed.ServerName, "server-name", "Sendspin Conformance Server", "")
	flag.Float64Var(&parsed.ClipSeconds, "clip-seconds", 5.0, "")
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
	if parsed.InitiatorRole != "client" {
		return exitWithSummary(parsed, errorSummary(parsed, "sendspin-go server only supports client-initiated scenarios"))
	}
	if !supportsScenario(parsed.ScenarioID) {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("sendspin-go server does not support %s", parsed.ScenarioID)))
	}

	var fixture *conformance.Fixture
	var err error
	if isPlayerScenario(parsed.ScenarioID) {
		fixture, err = conformance.DecodeFixture(parsed.Fixture, parsed.ClipSeconds)
		if err != nil {
			return exitWithSummary(parsed, errorSummary(parsed, err.Error()))
		}
	}

	listener, err := net.Listen("tcp", fmt.Sprintf("%s:%d", parsed.Host, parsed.Port))
	if err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to bind listener: %v", err)))
	}
	defer listener.Close()

	mux := http.NewServeMux()
	resultCh := make(chan sessionResult, 1)
	upgrader := websocket.Upgrader{
		CheckOrigin: func(_ *http.Request) bool { return true },
	}
	mux.HandleFunc("/sendspin", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			resultCh <- sessionResult{err: fmt.Errorf("failed to upgrade websocket: %w", err)}
			return
		}
		summary, err := runSession(conn, parsed, fixture)
		resultCh <- sessionResult{summary: summary, err: err}
	})

	server := &http.Server{Handler: mux}
	go func() {
		if serveErr := server.Serve(listener); serveErr != nil && serveErr != http.ErrServerClosed {
			resultCh <- sessionResult{err: serveErr}
		}
	}()

	url := fmt.Sprintf("ws://%s:%d/sendspin", parsed.Host, parsed.Port)
	if err := conformance.RegisterEndpoint(parsed.Registry, parsed.ServerName, url); err != nil {
		_ = server.Close()
		return exitWithSummary(parsed, errorSummary(parsed, fmt.Sprintf("failed to register endpoint: %v", err)))
	}
	if err := conformance.WriteJSON(parsed.Ready, map[string]any{
		"status":         "ready",
		"scenario_id":    parsed.ScenarioID,
		"initiator_role": parsed.InitiatorRole,
		"url":            url,
	}); err != nil {
		log.Printf("failed to write ready file: %v", err)
	}

	var result sessionResult
	select {
	case result = <-resultCh:
	case <-time.After(time.Duration(parsed.TimeoutSeconds * float64(time.Second))):
		result = sessionResult{err: fmt.Errorf("timed out waiting for client %q", parsed.ClientName)}
	}

	_ = server.Close()
	if result.err != nil {
		return exitWithSummary(parsed, errorSummary(parsed, result.err.Error()))
	}
	return exitWithSummary(parsed, result.summary)
}

func runSession(conn *websocket.Conn, parsed args, fixture *conformance.Fixture) (map[string]any, error) {
	defer conn.Close()

	_, helloBytes, err := conn.ReadMessage()
	if err != nil {
		return nil, fmt.Errorf("failed to read client/hello: %w", err)
	}
	rawPeerHello := decodeRawJSON(helloBytes)

	var envelope conformance.Envelope
	if err := json.Unmarshal(helloBytes, &envelope); err != nil {
		return nil, fmt.Errorf("invalid client/hello: %w", err)
	}
	if envelope.Type != "client/hello" {
		return nil, fmt.Errorf("expected client/hello, got %s", envelope.Type)
	}

	var hello protocol.ClientHello
	if err := json.Unmarshal(envelope.Payload, &hello); err != nil {
		return nil, fmt.Errorf("invalid client/hello payload: %w", err)
	}

	if hello.Name != parsed.ClientName {
		log.Printf("connected client name %q did not match expected %q", hello.Name, parsed.ClientName)
	}

	serverHello := protocol.ServerHello{
		ServerID:         parsed.ServerID,
		Name:             parsed.ServerName,
		Version:          1,
		ActiveRoles:      activeRoles(parsed.ScenarioID, hello.SupportedRoles),
		ConnectionReason: "playback",
	}
	if err := writeEnvelope(conn, "server/hello", serverHello); err != nil {
		return nil, fmt.Errorf("failed to write server/hello: %w", err)
	}

	var writeMu sync.Mutex
	readDone := make(chan struct{})
	readErrCh := make(chan error, 1)
	go readClientMessages(conn, &writeMu, readDone, readErrCh)

	if isPlayerScenario(parsed.ScenarioID) {
		streamStart := protocol.StreamStart{
			Player: &protocol.StreamStartPlayer{
				Codec:      "pcm",
				SampleRate: fixture.SampleRate,
				Channels:   fixture.Channels,
				BitDepth:   fixture.BitDepth,
			},
		}
		if err := sendJSON(conn, &writeMu, "stream/start", streamStart); err != nil {
			return nil, err
		}
		if err := sendJSON(conn, &writeMu, "server/state", metadataStateMessage(parsed)); err != nil {
			return nil, err
		}
		if err := sendJSON(conn, &writeMu, "group/update", protocol.GroupUpdate{
			GroupID:       ptr(parsed.ServerID),
			PlaybackState: ptr("playing"),
		}); err != nil {
			return nil, err
		}

		sentHasher := sha256.New()
		chunkCount := 0
		byteCount := 0
		nextTimestamp := conformance.CurrentMicros() + 250_000
		for _, block := range conformance.PCMBlocks(fixture.PCMBytes, fixture.SampleRate, fixture.Channels, fixture.BitDepth, 100) {
			if err := sendBinary(conn, &writeMu, audioChunk(nextTimestamp, block.Data)); err != nil {
				return nil, err
			}
			_, _ = sentHasher.Write(block.Data)
			chunkCount++
			byteCount += len(block.Data)
			nextTimestamp += block.DurationUS
			time.Sleep(5 * time.Millisecond)
		}

		_ = sendJSON(conn, &writeMu, "stream/end", protocol.StreamEnd{Roles: []string{"player"}})
		_ = sendClose(conn, &writeMu)
		<-readDone

		return map[string]any{
			"status":           "ok",
			"implementation":   "sendspin-go",
			"role":             "server",
			"server_id":        parsed.ServerID,
			"server_name":      parsed.ServerName,
			"scenario_id":      parsed.ScenarioID,
			"initiator_role":   parsed.InitiatorRole,
			"preferred_codec":  parsed.PreferredCodec,
			"discovery_method": "registry_advertised",
			"peer_hello":       rawPeerHello,
			"client": map[string]any{
				"client_id":       hello.ClientID,
				"name":            hello.Name,
				"supported_roles": hello.SupportedRoles,
			},
			"stream": map[string]any{
				"codec":       "pcm",
				"sample_rate": fixture.SampleRate,
				"channels":    fixture.Channels,
				"bit_depth":   fixture.BitDepth,
			},
			"audio": map[string]any{
				"fixture":                fixture.Path,
				"source_flac_sha256":     fixture.SourceFlacSHA256,
				"source_pcm_sha256":      fixture.SourcePcmSHA256,
				"sent_encoded_sha256":    conformance.HexLower(sentHasher.Sum(nil)),
				"sent_audio_chunk_count": chunkCount,
				"sent_encoded_byte_count": byteCount,
				"clip_seconds":            parsed.ClipSeconds,
				"sample_rate":             fixture.SampleRate,
				"channels":                fixture.Channels,
				"bit_depth":               fixture.BitDepth,
				"frame_count":             fixture.FrameCount,
				"duration_seconds":        fixture.DurationSeconds,
			},
		}, nil
	}

	if err := sendJSON(conn, &writeMu, "server/state", metadataStateMessage(parsed)); err != nil {
		return nil, err
	}
	_ = sendClose(conn, &writeMu)
	<-readDone

	if err := drainReadError(readErrCh); err != nil {
		return nil, err
	}

	return map[string]any{
		"status":           "ok",
		"implementation":   "sendspin-go",
		"role":             "server",
		"server_id":        parsed.ServerID,
		"server_name":      parsed.ServerName,
		"scenario_id":      parsed.ScenarioID,
		"initiator_role":   parsed.InitiatorRole,
		"preferred_codec":  parsed.PreferredCodec,
		"discovery_method": "registry_advertised",
		"peer_hello":       rawPeerHello,
		"client": map[string]any{
			"client_id":       hello.ClientID,
			"name":            hello.Name,
			"supported_roles": hello.SupportedRoles,
		},
		"metadata": map[string]any{
			"expected": metadataSnapshot(parsed),
		},
	}, nil
}

func readClientMessages(conn *websocket.Conn, writeMu *sync.Mutex, done chan<- struct{}, errCh chan<- error) {
	defer close(done)
	for {
		messageType, payload, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				return
			}
			if !strings.Contains(strings.ToLower(err.Error()), "close") {
				errCh <- err
			}
			return
		}
		if messageType != websocket.TextMessage {
			continue
		}
		var envelope conformance.Envelope
		if err := json.Unmarshal(payload, &envelope); err != nil {
			continue
		}
		if envelope.Type != "client/time" {
			continue
		}
		var clientTime protocol.ClientTime
		if err := json.Unmarshal(envelope.Payload, &clientTime); err != nil {
			continue
		}
		_ = sendJSON(conn, writeMu, "server/time", protocol.ServerTime{
			ClientTransmitted: clientTime.ClientTransmitted,
			ServerReceived:    conformance.CurrentMicros(),
			ServerTransmitted: conformance.CurrentMicros(),
		})
	}
}

func drainReadError(errCh <-chan error) error {
	select {
	case err := <-errCh:
		return err
	default:
		return nil
	}
}

func supportsScenario(scenarioID string) bool {
	return isPlayerScenario(scenarioID) || scenarioID == "client-initiated-metadata"
}

func isPlayerScenario(scenarioID string) bool {
	return scenarioID == "client-initiated-pcm"
}

func metadataStateMessage(parsed args) protocol.ServerStateMessage {
	return protocol.ServerStateMessage{
		Metadata: &protocol.MetadataState{
			Timestamp:   conformance.CurrentMicros(),
			Title:       ptr(parsed.MetadataTitle),
			Artist:      ptr(parsed.MetadataArtist),
			AlbumArtist: ptr(parsed.MetadataAlbumArt),
			Album:       ptr(parsed.MetadataAlbum),
			ArtworkURL:  ptr(parsed.MetadataURL),
			Year:        intPtr(parsed.MetadataYear),
			Track:       intPtr(parsed.MetadataTrack),
			Repeat:      ptr(parsed.MetadataRepeat),
			Shuffle:     boolPtr(parsed.MetadataShuffle == "true"),
			Progress: &protocol.ProgressState{
				TrackProgress: parsed.MetadataProgress,
				TrackDuration: parsed.MetadataDuration,
				PlaybackSpeed: parsed.MetadataSpeed,
			},
		},
	}
}

func metadataSnapshot(parsed args) map[string]any {
	return map[string]any{
		"title":        parsed.MetadataTitle,
		"artist":       parsed.MetadataArtist,
		"album_artist": parsed.MetadataAlbumArt,
		"album":        parsed.MetadataAlbum,
		"artwork_url":  parsed.MetadataURL,
		"year":         parsed.MetadataYear,
		"track":        parsed.MetadataTrack,
		"repeat":       parsed.MetadataRepeat,
		"shuffle":      parsed.MetadataShuffle == "true",
		"progress": map[string]any{
			"track_progress": parsed.MetadataProgress,
			"track_duration": parsed.MetadataDuration,
			"playback_speed": parsed.MetadataSpeed,
		},
	}
}

func activeRoles(scenarioID string, supported []string) []string {
	families := map[string]bool{}
	if isPlayerScenario(scenarioID) {
		families["player"] = true
		families["metadata"] = true
	} else {
		families["metadata"] = true
	}
	roles := make([]string, 0, len(supported))
	seen := map[string]bool{}
	for _, role := range supported {
		family := role
		if index := strings.Index(role, "@"); index > 0 {
			family = role[:index]
		}
		if families[family] && !seen[family] {
			roles = append(roles, role)
			seen[family] = true
		}
	}
	return roles
}

func sendJSON(conn *websocket.Conn, writeMu *sync.Mutex, messageType string, payload any) error {
	writeMu.Lock()
	defer writeMu.Unlock()
	return writeEnvelope(conn, messageType, payload)
}

func sendBinary(conn *websocket.Conn, writeMu *sync.Mutex, payload []byte) error {
	writeMu.Lock()
	defer writeMu.Unlock()
	return conn.WriteMessage(websocket.BinaryMessage, payload)
}

func sendClose(conn *websocket.Conn, writeMu *sync.Mutex) error {
	writeMu.Lock()
	defer writeMu.Unlock()
	deadline := time.Now().Add(time.Second)
	return conn.WriteControl(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, "done"), deadline)
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

func audioChunk(timestamp int64, payload []byte) []byte {
	chunk := make([]byte, 9+len(payload))
	chunk[0] = audioChunkMessageType
	binary.BigEndian.PutUint64(chunk[1:9], uint64(timestamp))
	copy(chunk[9:], payload)
	return chunk
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
		"role":            "server",
		"server_id":       parsed.ServerID,
		"server_name":     parsed.ServerName,
		"scenario_id":     parsed.ScenarioID,
		"initiator_role":  parsed.InitiatorRole,
		"preferred_codec": parsed.PreferredCodec,
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

func ptr(value string) *string {
	return &value
}

func intPtr(value int) *int {
	return &value
}

func boolPtr(value bool) *bool {
	return &value
}

func init() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
}
