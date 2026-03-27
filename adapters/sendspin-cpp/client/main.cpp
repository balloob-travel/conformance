#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <functional>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <ArduinoJson.h>
#include <ixwebsocket/IXWebSocket.h>
#include <ixwebsocket/IXWebSocketServer.h>

#ifdef HAS_OPENSSL
#include <openssl/sha.h>
#else
// Minimal SHA-256 when OpenSSL is unavailable.
#include <array>
namespace {
struct Sha256Ctx {
    uint32_t state[8]{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint8_t buffer[64]{};
    size_t buffer_len{0};
    uint64_t total_len{0};

    static constexpr uint32_t K[64]{
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

    static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

    void transform(const uint8_t block[64]) {
        uint32_t w[64];
        for (int i = 0; i < 16; i++)
            w[i] = uint32_t(block[i*4]) << 24 | uint32_t(block[i*4+1]) << 16 |
                    uint32_t(block[i*4+2]) << 8 | uint32_t(block[i*4+3]);
        for (int i = 16; i < 64; i++) {
            uint32_t s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >> 3);
            uint32_t s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }
        uint32_t a=state[0],b=state[1],c=state[2],d=state[3],
                 e=state[4],f=state[5],g=state[6],h=state[7];
        for (int i = 0; i < 64; i++) {
            uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = h + S1 + ch + K[i] + w[i];
            uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + maj;
            h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }
        state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
        state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
    }

    void update(const uint8_t *data, size_t len) {
        total_len += len;
        while (len > 0) {
            size_t copy = std::min(len, size_t(64) - buffer_len);
            std::memcpy(buffer + buffer_len, data, copy);
            buffer_len += copy; data += copy; len -= copy;
            if (buffer_len == 64) { transform(buffer); buffer_len = 0; }
        }
    }

    std::array<uint8_t, 32> finalize() {
        uint64_t bits = total_len * 8;
        uint8_t pad = 0x80;
        update(&pad, 1);
        pad = 0;
        while (buffer_len != 56) update(&pad, 1);
        uint8_t len_be[8];
        for (int i = 7; i >= 0; i--) { len_be[i] = uint8_t(bits); bits >>= 8; }
        update(len_be, 8);
        std::array<uint8_t, 32> digest;
        for (int i = 0; i < 8; i++) {
            digest[i*4]   = uint8_t(state[i] >> 24);
            digest[i*4+1] = uint8_t(state[i] >> 16);
            digest[i*4+2] = uint8_t(state[i] >> 8);
            digest[i*4+3] = uint8_t(state[i]);
        }
        return digest;
    }
};
} // namespace
#endif

// Binary frame constants (Sendspin protocol).
static constexpr int BINARY_HEADER_SIZE = 9;
static constexpr int AUDIO_CHUNK_MESSAGE_TYPE = 4;
static constexpr int ARTWORK_CHANNEL0_MESSAGE_TYPE = 8;

struct Args {
    std::string client_name;
    std::string client_id;
    std::string summary;
    std::string ready;
    std::string registry;
    std::string scenario_id = "client-initiated-pcm";
    std::string initiator_role = "client";
    std::string preferred_codec = "pcm";
    std::string server_name = "Sendspin Conformance Server";
    std::string server_id = "conformance-server";
    double timeout_seconds = 30.0;
    int port = 8928;
    std::string path = "/sendspin";
    std::string log_level = "info";
    std::string metadata_title = "Almost Silent";
    std::string metadata_artist = "Sendspin Conformance";
    std::string metadata_album_artist = "Sendspin";
    std::string metadata_album = "Protocol Fixtures";
    std::string metadata_artwork_url = "https://example.invalid/almost-silent.jpg";
    int metadata_year = 2026;
    int metadata_track = 1;
    std::string metadata_repeat = "all";
    std::string metadata_shuffle = "false";
    int metadata_track_progress = 12000;
    int metadata_track_duration = 180000;
    int metadata_playback_speed = 1000;
    std::string controller_command = "next";
    std::string artwork_format = "jpeg";
    int artwork_width = 256;
    int artwork_height = 256;
};

// SHA-256 helper wrapping either OpenSSL or the built-in implementation.
class Sha256Hasher {
public:
    void update(const uint8_t *data, size_t len) {
#ifdef HAS_OPENSSL
        SHA256_Update(&ctx_, data, len);
#else
        ctx_.update(data, len);
#endif
    }

    std::string hexdigest() const {
#ifdef HAS_OPENSSL
        unsigned char hash[SHA256_DIGEST_LENGTH];
        SHA256_CTX copy = ctx_;
        SHA256_Final(hash, &copy);
        return hex_lower(hash, SHA256_DIGEST_LENGTH);
#else
        auto copy = ctx_;
        auto digest = copy.finalize();
        return hex_lower(digest.data(), digest.size());
#endif
    }

private:
    static std::string hex_lower(const unsigned char *data, size_t len) {
        static const char hex[] = "0123456789abcdef";
        std::string out;
        out.reserve(len * 2);
        for (size_t i = 0; i < len; i++) {
            out.push_back(hex[data[i] >> 4]);
            out.push_back(hex[data[i] & 0xf]);
        }
        return out;
    }

#ifdef HAS_OPENSSL
    SHA256_CTX ctx_ = [] { SHA256_CTX c; SHA256_Init(&c); return c; }();
#else
    Sha256Ctx ctx_;
#endif
};

// Float PCM hasher (canonical float32 hash, matching the other adapters).
class FloatPcmHasher {
public:
    void update_from_pcm_bytes(const uint8_t *data, size_t len, int bit_depth) {
        if (bit_depth == 16) {
            for (size_t i = 0; i + 1 < len; i += 2) {
                int16_t sample = int16_t(uint16_t(data[i]) | (uint16_t(data[i + 1]) << 8));
                push_sample(float(sample) / 32768.0f);
            }
        } else if (bit_depth == 24) {
            for (size_t i = 0; i + 2 < len; i += 3) {
                int32_t value = int32_t(data[i]) | (int32_t(data[i + 1]) << 8) | (int32_t(data[i + 2]) << 16);
                if (value & 0x800000) value |= ~0x00FFFFFF;
                push_sample(float(value) / 8388608.0f);
            }
        } else if (bit_depth == 32) {
            for (size_t i = 0; i + 3 < len; i += 4) {
                int32_t sample = int32_t(uint32_t(data[i]) | (uint32_t(data[i + 1]) << 8) |
                                         (uint32_t(data[i + 2]) << 16) | (uint32_t(data[i + 3]) << 24));
                push_sample(float(sample) / 2147483648.0f);
            }
        }
    }

    std::string hexdigest() const { return hasher_.hexdigest(); }
    size_t sample_count() const { return sample_count_; }

private:
    void push_sample(float s) {
        uint8_t bytes[4];
        std::memcpy(bytes, &s, 4);
        hasher_.update(bytes, 4);
        sample_count_++;
    }

    Sha256Hasher hasher_;
    size_t sample_count_ = 0;
};

static bool is_player_scenario(const std::string &id) {
    return id == "client-initiated-pcm" || id == "server-initiated-pcm" || id == "server-initiated-flac";
}
static bool is_metadata_scenario(const std::string &id) {
    return id == "client-initiated-metadata" || id == "server-initiated-metadata";
}
static bool is_controller_scenario(const std::string &id) {
    return id == "client-initiated-controller" || id == "server-initiated-controller";
}
static bool is_artwork_scenario(const std::string &id) {
    return id == "client-initiated-artwork" || id == "server-initiated-artwork";
}

static std::string get_arg(int argc, char *argv[], const std::string &name, const std::string &def = "") {
    std::string flag = "--" + name;
    for (int i = 1; i < argc - 1; i++) {
        if (argv[i] == flag) return argv[i + 1];
    }
    return def;
}

static int get_int_arg(int argc, char *argv[], const std::string &name, int def) {
    std::string val = get_arg(argc, argv, name, "");
    return val.empty() ? def : std::stoi(val);
}

static double get_double_arg(int argc, char *argv[], const std::string &name, double def) {
    std::string val = get_arg(argc, argv, name, "");
    return val.empty() ? def : std::stod(val);
}

static Args parse_args(int argc, char *argv[]) {
    Args a;
    a.client_name = get_arg(argc, argv, "client-name");
    a.client_id = get_arg(argc, argv, "client-id");
    a.summary = get_arg(argc, argv, "summary");
    a.ready = get_arg(argc, argv, "ready");
    a.registry = get_arg(argc, argv, "registry");
    a.scenario_id = get_arg(argc, argv, "scenario-id", a.scenario_id);
    a.initiator_role = get_arg(argc, argv, "initiator-role", a.initiator_role);
    a.preferred_codec = get_arg(argc, argv, "preferred-codec", a.preferred_codec);
    a.server_name = get_arg(argc, argv, "server-name", a.server_name);
    a.server_id = get_arg(argc, argv, "server-id", a.server_id);
    a.timeout_seconds = get_double_arg(argc, argv, "timeout-seconds", a.timeout_seconds);
    a.port = get_int_arg(argc, argv, "port", a.port);
    a.path = get_arg(argc, argv, "path", a.path);
    a.log_level = get_arg(argc, argv, "log-level", a.log_level);
    a.metadata_title = get_arg(argc, argv, "metadata-title", a.metadata_title);
    a.metadata_artist = get_arg(argc, argv, "metadata-artist", a.metadata_artist);
    a.metadata_album_artist = get_arg(argc, argv, "metadata-album-artist", a.metadata_album_artist);
    a.metadata_album = get_arg(argc, argv, "metadata-album", a.metadata_album);
    a.metadata_artwork_url = get_arg(argc, argv, "metadata-artwork-url", a.metadata_artwork_url);
    a.metadata_year = get_int_arg(argc, argv, "metadata-year", a.metadata_year);
    a.metadata_track = get_int_arg(argc, argv, "metadata-track", a.metadata_track);
    a.metadata_repeat = get_arg(argc, argv, "metadata-repeat", a.metadata_repeat);
    a.metadata_shuffle = get_arg(argc, argv, "metadata-shuffle", a.metadata_shuffle);
    a.metadata_track_progress = get_int_arg(argc, argv, "metadata-track-progress", a.metadata_track_progress);
    a.metadata_track_duration = get_int_arg(argc, argv, "metadata-track-duration", a.metadata_track_duration);
    a.metadata_playback_speed = get_int_arg(argc, argv, "metadata-playback-speed", a.metadata_playback_speed);
    a.controller_command = get_arg(argc, argv, "controller-command", a.controller_command);
    a.artwork_format = get_arg(argc, argv, "artwork-format", a.artwork_format);
    a.artwork_width = get_int_arg(argc, argv, "artwork-width", a.artwork_width);
    a.artwork_height = get_int_arg(argc, argv, "artwork-height", a.artwork_height);
    return a;
}

static bool write_json_file(const std::string &path, const JsonDocument &doc) {
    std::ofstream out(path);
    if (!out) return false;
    serializeJsonPretty(doc, out);
    out << "\n";
    return out.good();
}

static void register_endpoint(const std::string &registry_path, const std::string &name, const std::string &url) {
    JsonDocument doc;
    {
        std::ifstream in(registry_path);
        if (in.good()) {
            deserializeJson(doc, in);
        }
    }
    doc[name]["url"] = url;
    write_json_file(registry_path, doc);
}

static std::string wait_for_server_url(const std::string &registry_path, const std::string &server_name,
                                       double timeout_s) {
    auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(int64_t(timeout_s * 1000));
    while (std::chrono::steady_clock::now() < deadline) {
        std::ifstream in(registry_path);
        if (in.good()) {
            JsonDocument doc;
            if (deserializeJson(doc, in) == DeserializationError::Ok) {
                const char *url = doc[server_name]["url"];
                if (url) return url;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return {};
}

static int64_t current_micros() {
    static auto start = std::chrono::steady_clock::now();
    return std::chrono::duration_cast<std::chrono::microseconds>(
               std::chrono::steady_clock::now() - start)
        .count();
}

static JsonDocument build_client_hello(const Args &args) {
    JsonDocument doc;
    doc["type"] = "client/hello";
    auto payload = doc["payload"].to<JsonObject>();
    payload["client_id"] = args.client_id;
    payload["name"] = args.client_name;
    payload["version"] = 1;

    auto device = payload["device_info"].to<JsonObject>();
    device["product_name"] = "sendspin-cpp Conformance Client";
    device["manufacturer"] = "Sendspin Conformance";
    device["software_version"] = "0.1.0";

    if (is_metadata_scenario(args.scenario_id)) {
        auto roles = payload["supported_roles"].to<JsonArray>();
        roles.add("metadata@v1");
    } else if (is_controller_scenario(args.scenario_id)) {
        auto roles = payload["supported_roles"].to<JsonArray>();
        roles.add("controller@v1");
    } else if (is_artwork_scenario(args.scenario_id)) {
        auto roles = payload["supported_roles"].to<JsonArray>();
        roles.add("artwork@v1");
        auto artwork = payload["artwork_v1_support"].to<JsonObject>();
        auto channels = artwork["channels"].to<JsonArray>();
        auto ch = channels.add<JsonObject>();
        ch["source"] = "album";
        ch["format"] = args.artwork_format;
        ch["media_width"] = args.artwork_width;
        ch["media_height"] = args.artwork_height;
    } else {
        auto roles = payload["supported_roles"].to<JsonArray>();
        roles.add("player@v1");
        auto player = payload["player_v1_support"].to<JsonObject>();
        auto formats = player["supported_formats"].to<JsonArray>();
        if (args.preferred_codec == "flac") {
            auto flac = formats.add<JsonObject>();
            flac["codec"] = "flac";
            flac["channels"] = 1;
            flac["sample_rate"] = 8000;
            flac["bit_depth"] = 16;
        }
        auto pcm = formats.add<JsonObject>();
        pcm["codec"] = "pcm";
        pcm["channels"] = 1;
        pcm["sample_rate"] = 8000;
        pcm["bit_depth"] = 16;
        player["buffer_capacity"] = 2000000;
        auto cmds = player["supported_commands"].to<JsonArray>();
        cmds.add("volume");
        cmds.add("mute");
    }
    return doc;
}

static JsonDocument build_client_state() {
    JsonDocument doc;
    doc["type"] = "client/state";
    auto payload = doc["payload"].to<JsonObject>();
    auto player = payload["player"].to<JsonObject>();
    player["state"] = "synchronized";
    player["volume"] = 100;
    player["muted"] = false;
    return doc;
}

static JsonDocument build_client_time() {
    JsonDocument doc;
    doc["type"] = "client/time";
    auto payload = doc["payload"].to<JsonObject>();
    payload["client_transmitted"] = current_micros();
    return doc;
}

static JsonDocument build_client_command(const std::string &command) {
    JsonDocument doc;
    doc["type"] = "client/command";
    auto payload = doc["payload"].to<JsonObject>();
    auto ctrl = payload["controller"].to<JsonObject>();
    ctrl["command"] = command;
    return doc;
}

static std::string serialize(const JsonDocument &doc) {
    std::string out;
    serializeJson(doc, out);
    return out;
}

struct SessionState {
    std::mutex mu;
    JsonDocument peer_hello;
    bool has_peer_hello = false;

    // Stream info
    std::string stream_codec;
    int stream_bit_depth = 16;
    JsonDocument stream_start_payload;
    bool has_stream = false;

    // Audio
    FloatPcmHasher pcm_hasher;
    Sha256Hasher encoded_hasher;
    int audio_chunk_count = 0;

    // Metadata
    int metadata_update_count = 0;
    JsonDocument received_metadata;
    bool has_metadata = false;

    // Controller
    JsonDocument received_controller_state;
    bool has_controller_state = false;
    JsonDocument sent_controller_command;
    bool has_sent_command = false;

    // Artwork
    JsonDocument artwork_stream;
    bool has_artwork_stream = false;
    int artwork_channel = -1;
    int artwork_count = 0;
    Sha256Hasher artwork_hasher;
    size_t artwork_byte_count = 0;

    std::string error_reason;
    bool done = false;
};

static void handle_text_message(const Args &args, SessionState &state, const std::string &text,
                                std::function<void(const std::string &)> send_text) {
    JsonDocument doc;
    auto err = deserializeJson(doc, text);
    if (err) {
        std::lock_guard<std::mutex> lock(state.mu);
        state.error_reason = std::string("Failed to parse server message: ") + err.c_str();
        state.done = true;
        return;
    }

    const char *type = doc["type"];
    if (!type) return;
    std::string msg_type(type);

    if (is_artwork_scenario(args.scenario_id) && msg_type == "stream/start") {
        std::lock_guard<std::mutex> lock(state.mu);
        state.artwork_stream = doc;
        state.has_artwork_stream = true;
        return;
    }

    if (msg_type == "stream/end" || msg_type == "group/update") return;

    if (msg_type == "server/hello") {
        std::lock_guard<std::mutex> lock(state.mu);
        state.peer_hello = doc;
        state.has_peer_hello = true;

        if (is_player_scenario(args.scenario_id)) {
            send_text(serialize(build_client_state()));
            send_text(serialize(build_client_time()));
        }
    } else if (msg_type == "server/state") {
        std::lock_guard<std::mutex> lock(state.mu);
        auto payload = doc["payload"];

        if (!payload["metadata"].isNull()) {
            state.metadata_update_count++;
            auto md = payload["metadata"];
            state.received_metadata.clear();
            state.received_metadata["title"] = md["title"];
            state.received_metadata["artist"] = md["artist"];
            state.received_metadata["album_artist"] = md["album_artist"];
            state.received_metadata["album"] = md["album"];
            state.received_metadata["artwork_url"] = md["artwork_url"];
            state.received_metadata["year"] = md["year"];
            state.received_metadata["track"] = md["track"];
            state.received_metadata["repeat"] = md["repeat"];
            state.received_metadata["shuffle"] = md["shuffle"];
            if (!md["progress"].isNull()) {
                auto progress = state.received_metadata["progress"].to<JsonObject>();
                progress["track_progress"] = md["progress"]["track_progress"];
                progress["track_duration"] = md["progress"]["track_duration"];
                progress["playback_speed"] = md["progress"]["playback_speed"];
            } else {
                state.received_metadata["progress"] = nullptr;
            }
            state.has_metadata = true;
        }

        if (!payload["controller"].isNull()) {
            auto ctrl = payload["controller"];
            state.received_controller_state.clear();
            state.received_controller_state["supported_commands"] = ctrl["supported_commands"];
            state.received_controller_state["volume"] = ctrl["volume"];
            state.received_controller_state["muted"] = ctrl["muted"];
            state.has_controller_state = true;

            if (is_controller_scenario(args.scenario_id) && !state.has_sent_command) {
                auto cmds = ctrl["supported_commands"];
                bool supports = false;
                if (cmds.is<JsonArray>()) {
                    for (auto cmd : cmds.as<JsonArray>()) {
                        if (cmd.as<std::string>() == args.controller_command) {
                            supports = true;
                            break;
                        }
                    }
                }
                if (supports) {
                    send_text(serialize(build_client_command(args.controller_command)));
                    state.sent_controller_command.clear();
                    state.sent_controller_command["command"] = args.controller_command;
                    state.has_sent_command = true;
                }
            }
        }
    } else if (msg_type == "stream/start") {
        std::lock_guard<std::mutex> lock(state.mu);
        auto player = doc["payload"]["player"];
        if (!player.isNull()) {
            state.stream_codec = player["codec"].as<std::string>();
            state.stream_bit_depth = player["bit_depth"] | 16;
            state.stream_start_payload = doc;
            state.has_stream = true;
        }
    } else if (msg_type == "server/time" || msg_type == "server/command" || msg_type == "stream/clear") {
        // Ignored
    }
}

static void handle_binary_message(const Args &args, SessionState &state,
                                  const std::string &data) {
    if (data.size() < size_t(BINARY_HEADER_SIZE)) return;

    int message_code = uint8_t(data[0]);
    const uint8_t *payload = reinterpret_cast<const uint8_t *>(data.data() + BINARY_HEADER_SIZE);
    size_t payload_len = data.size() - BINARY_HEADER_SIZE;

    if (is_artwork_scenario(args.scenario_id) &&
        message_code >= ARTWORK_CHANNEL0_MESSAGE_TYPE &&
        message_code <= ARTWORK_CHANNEL0_MESSAGE_TYPE + 3) {
        std::lock_guard<std::mutex> lock(state.mu);
        state.artwork_channel = message_code - ARTWORK_CHANNEL0_MESSAGE_TYPE;
        state.artwork_count++;
        state.artwork_byte_count += payload_len;
        state.artwork_hasher.update(payload, payload_len);
        return;
    }

    if (!is_player_scenario(args.scenario_id)) return;
    if (message_code != AUDIO_CHUNK_MESSAGE_TYPE) return;

    std::lock_guard<std::mutex> lock(state.mu);
    if (!state.has_stream) {
        state.error_reason = "Received audio before stream/start";
        state.done = true;
        return;
    }

    state.encoded_hasher.update(payload, payload_len);
    if (state.stream_codec == "pcm") {
        state.pcm_hasher.update_from_pcm_bytes(payload, payload_len, state.stream_bit_depth);
    } else if (state.stream_codec != "flac") {
        state.error_reason = "Unsupported codec: " + state.stream_codec;
        state.done = true;
        return;
    }
    state.audio_chunk_count++;
}

static JsonDocument build_summary(const Args &args, const SessionState &state, const std::string &status,
                                  const std::string &reason) {
    JsonDocument doc;
    doc["status"] = status;
    if (reason.empty())
        doc["reason"] = nullptr;
    else
        doc["reason"] = reason;
    doc["implementation"] = "sendspin-cpp";
    doc["role"] = "client";
    doc["scenario_id"] = args.scenario_id;
    doc["initiator_role"] = args.initiator_role;
    doc["preferred_codec"] = args.preferred_codec;
    doc["client_name"] = args.client_name;
    doc["client_id"] = args.client_id;

    if (state.has_peer_hello) {
        doc["peer_hello"] = state.peer_hello;
        auto payload = state.peer_hello["payload"];
        if (!payload.isNull()) {
            auto server = doc["server"].to<JsonObject>();
            server["server_id"] = payload["server_id"];
            server["name"] = payload["name"];
            server["version"] = payload["version"];
            server["active_roles"] = payload["active_roles"];
            server["connection_reason"] = payload["connection_reason"];
        }
    } else {
        doc["peer_hello"] = nullptr;
        doc["server"] = nullptr;
    }

    if (is_metadata_scenario(args.scenario_id)) {
        auto metadata = doc["metadata"].to<JsonObject>();
        metadata["update_count"] = state.metadata_update_count;
        if (state.has_metadata)
            metadata["received"] = state.received_metadata;
        else
            metadata["received"] = nullptr;
    } else if (is_controller_scenario(args.scenario_id)) {
        auto ctrl = doc["controller"].to<JsonObject>();
        if (state.has_controller_state)
            ctrl["received_state"] = state.received_controller_state;
        else
            ctrl["received_state"] = nullptr;
        if (state.has_sent_command)
            ctrl["sent_command"] = state.sent_controller_command;
        else
            ctrl["sent_command"] = nullptr;
    } else if (is_artwork_scenario(args.scenario_id)) {
        if (state.has_artwork_stream) {
            auto payload = state.artwork_stream["payload"];
            if (!payload.isNull() && !payload["artwork"].isNull())
                doc["stream"] = payload["artwork"];
            else
                doc["stream"] = nullptr;
        } else {
            doc["stream"] = nullptr;
        }
        auto artwork = doc["artwork"].to<JsonObject>();
        if (state.artwork_channel >= 0)
            artwork["channel"] = state.artwork_channel;
        else
            artwork["channel"] = nullptr;
        artwork["received_count"] = state.artwork_count;
        if (state.artwork_count > 0) {
            artwork["received_sha256"] = state.artwork_hasher.hexdigest();
        } else {
            artwork["received_sha256"] = nullptr;
        }
        artwork["byte_count"] = state.artwork_byte_count;
    } else {
        // Player scenario
        if (state.has_stream) {
            auto stream = doc["stream"].to<JsonObject>();
            auto player = state.stream_start_payload["payload"]["player"];
            stream["codec"] = player["codec"];
            stream["sample_rate"] = player["sample_rate"];
            stream["channels"] = player["channels"];
            stream["bit_depth"] = player["bit_depth"];
            stream["codec_header"] = player["codec_header"];
        } else {
            doc["stream"] = nullptr;
        }
        auto audio = doc["audio"].to<JsonObject>();
        audio["audio_chunk_count"] = state.audio_chunk_count;
        if (state.audio_chunk_count > 0) {
            audio["received_encoded_sha256"] = state.encoded_hasher.hexdigest();
            audio["received_pcm_sha256"] = state.pcm_hasher.hexdigest();
        } else {
            audio["received_encoded_sha256"] = nullptr;
            audio["received_pcm_sha256"] = nullptr;
        }
        audio["received_sample_count"] = state.pcm_hasher.sample_count();
    }

    return doc;
}

static int run_client_initiated(const Args &args) {
    std::string server_url = wait_for_server_url(args.registry, args.server_name, args.timeout_seconds);
    if (server_url.empty()) {
        SessionState empty;
        auto summary = build_summary(args, empty, "error",
                                     "Timed out waiting for server " + args.server_name);
        write_json_file(args.summary, summary);
        return 1;
    }

    SessionState state;
    std::atomic<bool> connected{false};
    std::atomic<bool> closed{false};

    ix::WebSocket ws;
    ws.setUrl(server_url);
    ws.disableAutomaticReconnection();
    ws.setPingInterval(0);

    ws.setOnMessageCallback([&](const ix::WebSocketMessagePtr &msg) {
        auto send_text = [&](const std::string &text) {
            ws.send(text);
        };

        switch (msg->type) {
        case ix::WebSocketMessageType::Open:
            connected = true;
            ws.send(serialize(build_client_hello(args)));
            break;
        case ix::WebSocketMessageType::Message:
            if (msg->binary) {
                handle_binary_message(args, state, msg->str);
            } else {
                handle_text_message(args, state, msg->str, send_text);
            }
            break;
        case ix::WebSocketMessageType::Close:
            closed = true;
            break;
        case ix::WebSocketMessageType::Error: {
            std::lock_guard<std::mutex> lock(state.mu);
            state.error_reason = "WebSocket error: " + msg->errorInfo.reason;
            state.done = true;
            closed = true;
            break;
        }
        default:
            break;
        }
    });

    ws.start();

    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::milliseconds(int64_t(args.timeout_seconds * 1000));
    while (!closed && !state.done && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    ws.stop();

    std::string status, reason;
    {
        std::lock_guard<std::mutex> lock(state.mu);
        if (!state.error_reason.empty()) {
            status = "error";
            reason = state.error_reason;
        } else if (!state.has_peer_hello) {
            status = "error";
            reason = "Connection closed before handshake completed";
        } else if (!closed && std::chrono::steady_clock::now() >= deadline) {
            status = "error";
            reason = "Timed out waiting for server disconnect";
        } else {
            status = "ok";
        }
    }

    auto summary = build_summary(args, state, status, reason);
    write_json_file(args.summary, summary);
    std::string out;
    serializeJson(summary, out);
    std::cout << out;
    return status == "ok" ? 0 : 1;
}

static int run_server_initiated(const Args &args) {
    std::string bind_host = "127.0.0.1";
    std::string url = "ws://" + bind_host + ":" + std::to_string(args.port) + args.path;

    SessionState state;
    std::atomic<bool> got_connection{false};
    std::atomic<bool> closed{false};

    ix::WebSocketServer server(args.port, bind_host);
    server.disablePerMessageDeflate();

    server.setOnClientMessageCallback(
        [&](std::shared_ptr<ix::ConnectionState> /*connState*/,
            ix::WebSocket &client_ws,
            const ix::WebSocketMessagePtr &msg) {
            auto send_text = [&](const std::string &text) {
                client_ws.send(text);
            };

            switch (msg->type) {
            case ix::WebSocketMessageType::Open:
                got_connection = true;
                client_ws.send(serialize(build_client_hello(args)));
                break;
            case ix::WebSocketMessageType::Message:
                if (msg->binary) {
                    handle_binary_message(args, state, msg->str);
                } else {
                    handle_text_message(args, state, msg->str, send_text);
                }
                break;
            case ix::WebSocketMessageType::Close:
                closed = true;
                break;
            case ix::WebSocketMessageType::Error: {
                std::lock_guard<std::mutex> lock(state.mu);
                state.error_reason = "WebSocket error: " + msg->errorInfo.reason;
                state.done = true;
                closed = true;
                break;
            }
            default:
                break;
            }
        });

    auto [ok, err_msg] = server.listen();
    if (!ok) {
        SessionState empty;
        auto summary = build_summary(args, empty, "error", "Failed to listen: " + err_msg);
        write_json_file(args.summary, summary);
        return 1;
    }

    server.start();
    register_endpoint(args.registry, args.client_name, url);

    // Write ready file
    {
        JsonDocument ready_doc;
        ready_doc["status"] = "ready";
        ready_doc["scenario_id"] = args.scenario_id;
        ready_doc["initiator_role"] = args.initiator_role;
        ready_doc["url"] = url;
        write_json_file(args.ready, ready_doc);
    }

    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::milliseconds(int64_t(args.timeout_seconds * 1000));
    while (!closed && !state.done && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    server.stop();

    std::string status, reason;
    {
        std::lock_guard<std::mutex> lock(state.mu);
        if (!state.error_reason.empty()) {
            status = "error";
            reason = state.error_reason;
        } else if (!got_connection) {
            status = "error";
            reason = "Timed out waiting for server connection";
        } else if (!state.has_peer_hello) {
            status = "error";
            reason = "Connection closed before handshake completed";
        } else if (!closed && std::chrono::steady_clock::now() >= deadline) {
            status = "error";
            reason = "Timed out waiting for server disconnect";
        } else {
            status = "ok";
        }
    }

    auto summary = build_summary(args, state, status, reason);
    write_json_file(args.summary, summary);
    std::string out;
    serializeJson(summary, out);
    std::cout << out;
    return status == "ok" ? 0 : 1;
}

int main(int argc, char *argv[]) {
    ix::initNetSystem();
    Args args = parse_args(argc, argv);

    if (args.initiator_role == "client") {
        // Write ready file before waiting for server
        JsonDocument ready_doc;
        ready_doc["status"] = "ready";
        ready_doc["scenario_id"] = args.scenario_id;
        ready_doc["initiator_role"] = args.initiator_role;
        write_json_file(args.ready, ready_doc);

        int ret = run_client_initiated(args);
        ix::uninitNetSystem();
        return ret;
    }

    int ret = run_server_initiated(args);
    ix::uninitNetSystem();
    return ret;
}
