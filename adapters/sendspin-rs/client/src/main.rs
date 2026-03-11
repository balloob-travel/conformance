use clap::Parser;
use futures_util::{SinkExt, StreamExt};
use sendspin::protocol::client::{AudioChunk, ArtworkChunk, BinaryFrame};
use sendspin::protocol::messages::{
    ArtworkChannel, ArtworkSource, ArtworkV1Support, AudioFormatSpec, ClientCommand,
    ClientHello, ClientState, ClientTime, ControllerCommand, ControllerState, DeviceInfo,
    ImageFormat, Message, MetadataState, PlayerState, PlayerSyncState, PlayerV1Support,
    ServerHello, StreamPlayerConfig,
};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tokio::time::sleep;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message as WsMessage;

#[derive(Parser, Debug, Clone)]
struct Args {
    #[arg(long)]
    client_name: String,
    #[arg(long)]
    client_id: String,
    #[arg(long)]
    summary: PathBuf,
    #[arg(long)]
    ready: PathBuf,
    #[arg(long)]
    registry: PathBuf,
    #[arg(long, default_value = "client-initiated-pcm")]
    scenario_id: String,
    #[arg(long, default_value = "client")]
    initiator_role: String,
    #[arg(long, default_value = "pcm")]
    preferred_codec: String,
    #[arg(long, default_value = "Sendspin Conformance Server")]
    server_name: String,
    #[arg(long, default_value = "conformance-server")]
    server_id: String,
    #[arg(long, default_value_t = 30.0)]
    timeout_seconds: f64,
    #[arg(long, default_value = "info")]
    log_level: String,
    #[arg(long, default_value = "Almost Silent")]
    metadata_title: String,
    #[arg(long, default_value = "Sendspin Conformance")]
    metadata_artist: String,
    #[arg(long, default_value = "Sendspin")]
    metadata_album_artist: String,
    #[arg(long, default_value = "Protocol Fixtures")]
    metadata_album: String,
    #[arg(long, default_value = "https://example.invalid/almost-silent.jpg")]
    metadata_artwork_url: String,
    #[arg(long, default_value_t = 2026)]
    metadata_year: i32,
    #[arg(long, default_value_t = 1)]
    metadata_track: i32,
    #[arg(long, default_value = "all")]
    metadata_repeat: String,
    #[arg(long, default_value = "false")]
    metadata_shuffle: String,
    #[arg(long, default_value_t = 12_000)]
    metadata_track_progress: i64,
    #[arg(long, default_value_t = 180_000)]
    metadata_track_duration: i64,
    #[arg(long, default_value_t = 1_000)]
    metadata_playback_speed: i32,
    #[arg(long, default_value = "next")]
    controller_command: String,
    #[arg(long, default_value = "jpeg")]
    artwork_format: String,
    #[arg(long, default_value_t = 256)]
    artwork_width: u32,
    #[arg(long, default_value_t = 256)]
    artwork_height: u32,
}

#[derive(Default)]
struct FloatPcmHasher {
    hasher: Sha256,
    sample_count: usize,
}

impl FloatPcmHasher {
    fn update_from_pcm_bytes(&mut self, pcm_bytes: &[u8], bit_depth: u8) -> Result<(), String> {
        match bit_depth {
            16 => {
                for chunk in pcm_bytes.chunks_exact(2) {
                    let sample = i16::from_le_bytes([chunk[0], chunk[1]]) as f32 / 32768.0;
                    self.hasher.update(sample.to_le_bytes());
                    self.sample_count += 1;
                }
                Ok(())
            }
            24 => {
                for chunk in pcm_bytes.chunks_exact(3) {
                    let mut value =
                        (chunk[0] as i32) | ((chunk[1] as i32) << 8) | ((chunk[2] as i32) << 16);
                    if value & 0x800000 != 0 {
                        value |= !0x00FF_FFFF;
                    }
                    let sample = value as f32 / 8_388_608.0;
                    self.hasher.update(sample.to_le_bytes());
                    self.sample_count += 1;
                }
                Ok(())
            }
            32 => {
                for chunk in pcm_bytes.chunks_exact(4) {
                    let sample = i32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]) as f32
                        / 2_147_483_648.0;
                    self.hasher.update(sample.to_le_bytes());
                    self.sample_count += 1;
                }
                Ok(())
            }
            _ => Err(format!("Unsupported PCM bit depth: {bit_depth}")),
        }
    }

    fn hexdigest(&self) -> String {
        let digest = self.hasher.clone().finalize();
        hex_lower(&digest)
    }
}

fn hex_lower(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push_str(&format!("{byte:02x}"));
    }
    output
}

fn write_json(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let content = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    fs::write(path, format!("{content}\n")).map_err(|err| err.to_string())
}

fn current_micros() -> i64 {
    static PROCESS_START: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();
    let start = PROCESS_START.get_or_init(Instant::now);
    start.elapsed().as_micros() as i64
}

async fn wait_for_server_url(
    registry_path: &Path,
    server_name: &str,
    timeout_s: f64,
) -> Result<String, String> {
    let deadline = Instant::now() + Duration::from_secs_f64(timeout_s);
    while Instant::now() < deadline {
        if let Ok(content) = fs::read_to_string(registry_path) {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(url) = value
                    .get(server_name)
                    .and_then(|entry| entry.get("url"))
                    .and_then(|url| url.as_str())
                {
                    return Ok(url.to_string());
                }
            }
        }
        sleep(Duration::from_millis(100)).await;
    }
    Err(format!("Timed out waiting for server {server_name:?}"))
}

fn build_client_hello(args: &Args) -> ClientHello {
    let (supported_roles, player_v1_support, artwork_v1_support) = match args.scenario_id.as_str() {
        "client-initiated-metadata" => (vec!["metadata@v1".to_string()], None, None),
        "client-initiated-controller" => (vec!["controller@v1".to_string()], None, None),
        "client-initiated-artwork" => (
            vec!["artwork@v1".to_string()],
            None,
            Some(ArtworkV1Support {
                channels: vec![ArtworkChannel {
                    source: ArtworkSource::Album,
                    format: match args.artwork_format.as_str() {
                        "png" => ImageFormat::Png,
                        "bmp" => ImageFormat::Bmp,
                        _ => ImageFormat::Jpeg,
                    },
                    media_width: args.artwork_width,
                    media_height: args.artwork_height,
                }],
            }),
        ),
        _ => (
            vec!["player@v1".to_string()],
            Some(PlayerV1Support {
                supported_formats: if args.preferred_codec == "pcm" {
                    vec![AudioFormatSpec {
                        codec: "pcm".to_string(),
                        channels: 1,
                        sample_rate: 8000,
                        bit_depth: 16,
                    }]
                } else {
                    vec![
                        AudioFormatSpec {
                            codec: "flac".to_string(),
                            channels: 1,
                            sample_rate: 8000,
                            bit_depth: 16,
                        },
                        AudioFormatSpec {
                            codec: "pcm".to_string(),
                            channels: 1,
                            sample_rate: 8000,
                            bit_depth: 16,
                        },
                    ]
                },
                buffer_capacity: 2_000_000,
                supported_commands: vec!["volume".to_string(), "mute".to_string()],
            }),
            None,
        ),
    };

    ClientHello {
        client_id: args.client_id.clone(),
        name: args.client_name.clone(),
        version: 1,
        supported_roles,
        device_info: Some(DeviceInfo {
            product_name: Some("sendspin-rs Conformance Client".to_string()),
            manufacturer: Some("Sendspin Conformance".to_string()),
            software_version: Some("0.1.0".to_string()),
        }),
        player_v1_support,
        artwork_v1_support,
        visualizer_v1_support: None,
    }
}

fn normalize_metadata(metadata: &MetadataState) -> serde_json::Value {
    serde_json::json!({
        "title": metadata.title,
        "artist": metadata.artist,
        "album_artist": metadata.album_artist,
        "album": metadata.album,
        "artwork_url": metadata.artwork_url,
        "year": metadata.year,
        "track": metadata.track,
        "repeat": metadata.repeat,
        "shuffle": metadata.shuffle,
        "progress": metadata.progress.as_ref().map(|progress| serde_json::json!({
            "track_progress": progress.track_progress,
            "track_duration": progress.track_duration,
            "playback_speed": progress.playback_speed,
        })),
    })
}

fn normalize_controller(controller: &ControllerState) -> serde_json::Value {
    serde_json::json!({
        "supported_commands": controller.supported_commands,
        "volume": controller.volume,
        "muted": controller.muted,
    })
}

fn build_summary(
    args: &Args,
    status: &str,
    reason: Option<&str>,
    peer_hello: Option<serde_json::Value>,
    server_hello: Option<&ServerHello>,
    current_stream: Option<&StreamPlayerConfig>,
    audio_chunk_count: usize,
    received_encoded_sha256: Option<String>,
    received_pcm_sha256: Option<String>,
    received_sample_count: usize,
    metadata_update_count: usize,
    received_metadata: Option<serde_json::Value>,
    received_controller_state: Option<serde_json::Value>,
    sent_controller_command: Option<serde_json::Value>,
    artwork_stream: Option<serde_json::Value>,
    artwork_channel: Option<u8>,
    artwork_count: usize,
    artwork_sha256: Option<String>,
    artwork_byte_count: usize,
) -> serde_json::Value {
    let mut summary = serde_json::json!({
        "status": status,
        "reason": reason,
        "implementation": "sendspin-rs",
        "role": "client",
        "scenario_id": args.scenario_id,
        "initiator_role": args.initiator_role,
        "preferred_codec": args.preferred_codec,
        "client_name": args.client_name,
        "client_id": args.client_id,
        "peer_hello": peer_hello,
        "server": server_hello.map(|hello| {
            serde_json::json!({
                "server_id": hello.server_id,
                "name": hello.name,
                "version": hello.version,
                "active_roles": hello.active_roles,
                "connection_reason": hello.connection_reason,
            })
        }).or_else(|| peer_hello.as_ref().and_then(|hello| hello.get("payload")).cloned()),
    });

    match args.scenario_id.as_str() {
        "client-initiated-metadata" => {
            summary["metadata"] = serde_json::json!({
                "update_count": metadata_update_count,
                "received": received_metadata,
            });
        }
        "client-initiated-controller" => {
            summary["controller"] = serde_json::json!({
                "received_state": received_controller_state,
                "sent_command": sent_controller_command,
            });
        }
        "client-initiated-artwork" => {
            summary["stream"] = artwork_stream.unwrap_or(serde_json::Value::Null);
            summary["artwork"] = serde_json::json!({
                "channel": artwork_channel,
                "received_count": artwork_count,
                "received_sha256": artwork_sha256,
                "byte_count": artwork_byte_count,
            });
        }
        _ => {
            summary["stream"] = current_stream.map(|stream| serde_json::json!({
                "codec": stream.codec,
                "sample_rate": stream.sample_rate,
                "channels": stream.channels,
                "bit_depth": stream.bit_depth,
                "codec_header": stream.codec_header,
            })).unwrap_or(serde_json::Value::Null);
            summary["audio"] = serde_json::json!({
                "audio_chunk_count": audio_chunk_count,
                "received_encoded_sha256": received_encoded_sha256,
                "received_pcm_sha256": received_pcm_sha256,
                "received_sample_count": received_sample_count,
            });
        }
    }

    summary
}

async fn run(args: Args) -> Result<(), String> {
    if args.initiator_role != "client" {
        let summary = build_summary(
            &args,
            "error",
            Some("sendspin-rs client adapter only supports client-initiated scenarios"),
            None,
            None,
            None,
            0,
            None,
            None,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            0,
            None,
            0,
        );
        write_json(&args.summary, &summary)?;
        print!("{summary}");
        return Err("sendspin-rs client adapter only supports client-initiated scenarios".to_string());
    }

    let ready = serde_json::json!({
        "status": "ready",
        "scenario_id": args.scenario_id,
        "initiator_role": args.initiator_role,
    });
    write_json(&args.ready, &ready)?;

    let server_url = wait_for_server_url(&args.registry, &args.server_name, args.timeout_seconds).await?;
    let (ws_stream, _) = connect_async(&server_url)
        .await
        .map_err(|err| format!("Failed to connect to {server_url}: {err}"))?;
    let (mut write, mut read) = ws_stream.split();

    let hello = Message::ClientHello(build_client_hello(&args));
    let hello_json = serde_json::to_string(&hello).map_err(|err| err.to_string())?;
    write
        .send(WsMessage::Text(hello_json))
        .await
        .map_err(|err| err.to_string())?;

    let mut peer_hello: Option<serde_json::Value> = None;
    let mut server_hello_payload: Option<ServerHello> = None;
    let mut current_stream: Option<StreamPlayerConfig> = None;
    let mut received_hasher = FloatPcmHasher::default();
    let mut encoded_hasher = Sha256::new();
    let mut audio_chunk_count = 0usize;
    let mut metadata_update_count = 0usize;
    let mut received_metadata: Option<serde_json::Value> = None;
    let mut received_controller_state: Option<serde_json::Value> = None;
    let mut sent_controller_command: Option<serde_json::Value> = None;
    let mut artwork_stream: Option<serde_json::Value> = None;
    let mut artwork_channel: Option<u8> = None;
    let mut artwork_count = 0usize;
    let mut artwork_hasher = Sha256::new();
    let mut artwork_byte_count = 0usize;
    let timeout = Duration::from_secs_f64(args.timeout_seconds);

    let read_result = tokio::time::timeout(timeout, async {
        loop {
            let Some(frame) = read.next().await else {
                break;
            };

            match frame.map_err(|err| err.to_string())? {
                WsMessage::Text(text) => {
                    let raw_value = serde_json::from_str::<serde_json::Value>(&text)
                        .map_err(|err| err.to_string())?;
                    let message_type = raw_value
                        .get("type")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default();
                    if args.scenario_id == "client-initiated-artwork" && message_type == "stream/start"
                    {
                        artwork_stream = raw_value
                            .get("payload")
                            .and_then(|payload| payload.get("artwork"))
                            .cloned();
                        continue;
                    }
                    if message_type == "stream/end" {
                        continue;
                    }
                    let message =
                        serde_json::from_str::<Message>(&text).map_err(|err| err.to_string())?;
                    match message {
                        Message::ServerHello(server_hello) => {
                            peer_hello = Some(raw_value);
                            server_hello_payload = Some(server_hello);
                            if args.scenario_id == "client-initiated-pcm"
                                || args.scenario_id == "server-initiated-flac"
                            {
                                let state = Message::ClientState(ClientState {
                                    player: Some(PlayerState {
                                        state: PlayerSyncState::Synchronized,
                                        volume: Some(100),
                                        muted: Some(false),
                                    }),
                                });
                                let state_json =
                                    serde_json::to_string(&state).map_err(|err| err.to_string())?;
                                write
                                    .send(WsMessage::Text(state_json))
                                    .await
                                    .map_err(|err| err.to_string())?;
                                let time_sync = Message::ClientTime(ClientTime {
                                    client_transmitted: current_micros(),
                                });
                                let time_json = serde_json::to_string(&time_sync)
                                    .map_err(|err| err.to_string())?;
                                write
                                    .send(WsMessage::Text(time_json))
                                    .await
                                    .map_err(|err| err.to_string())?;
                            }
                        }
                        Message::ServerState(server_state) => {
                            if let Some(metadata) = server_state.metadata.as_ref() {
                                metadata_update_count += 1;
                                received_metadata = Some(normalize_metadata(metadata));
                            }
                            if let Some(controller) = server_state.controller.as_ref() {
                                received_controller_state = Some(normalize_controller(controller));
                                if args.scenario_id == "client-initiated-controller"
                                    && sent_controller_command.is_none()
                                    && controller
                                        .supported_commands
                                        .contains(&args.controller_command)
                                {
                                    let command = Message::ClientCommand(ClientCommand {
                                        controller: Some(ControllerCommand {
                                            command: args.controller_command.clone(),
                                            volume: None,
                                            mute: None,
                                        }),
                                    });
                                    let command_json = serde_json::to_string(&command)
                                        .map_err(|err| err.to_string())?;
                                    write
                                        .send(WsMessage::Text(command_json))
                                        .await
                                        .map_err(|err| err.to_string())?;
                                    sent_controller_command = Some(serde_json::json!({
                                        "command": args.controller_command,
                                    }));
                                }
                            }
                        }
                        Message::StreamStart(stream_start) => {
                            current_stream = stream_start.player;
                        }
                        Message::ServerTime(_)
                        | Message::GroupUpdate(_)
                        | Message::ServerCommand(_)
                        | Message::StreamClear(_) => {}
                        other => {
                            return Err(format!("Unexpected server message: {other:?}"));
                        }
                    }
                }
                WsMessage::Binary(data) => {
                    match BinaryFrame::from_bytes(&data).map_err(|err| err.to_string())? {
                        BinaryFrame::Audio(AudioChunk { data, .. }) => {
                            if args.scenario_id != "client-initiated-pcm"
                                && args.scenario_id != "server-initiated-flac"
                            {
                                continue;
                            }
                            let stream = current_stream
                                .as_ref()
                                .ok_or_else(|| "Received audio before stream/start".to_string())?;
                            if stream.codec != "pcm" {
                                return Err(format!(
                                    "Unsupported codec for current scenario: {}",
                                    stream.codec
                                ));
                            }
                            encoded_hasher.update(&*data);
                            received_hasher
                                .update_from_pcm_bytes(&data, stream.bit_depth)
                                .map_err(|err| err.to_string())?;
                            audio_chunk_count += 1;
                        }
                        BinaryFrame::Artwork(ArtworkChunk { channel, data, .. }) => {
                            if args.scenario_id != "client-initiated-artwork" {
                                continue;
                            }
                            artwork_channel = Some(channel);
                            artwork_count += 1;
                            artwork_byte_count += data.len();
                            artwork_hasher.update(&*data);
                        }
                        BinaryFrame::Visualizer(_) | BinaryFrame::Unknown { .. } => {}
                    }
                }
                WsMessage::Ping(payload) => {
                    write
                        .send(WsMessage::Pong(payload))
                        .await
                        .map_err(|err| err.to_string())?;
                }
                WsMessage::Close(_) => break,
                _ => {}
            }
        }
        Ok::<(), String>(())
    })
    .await;

    let received_encoded_sha256 = if audio_chunk_count > 0 {
        Some(hex_lower(&encoded_hasher.clone().finalize()))
    } else {
        None
    };
    let received_pcm_sha256 = if received_hasher.sample_count > 0 {
        Some(received_hasher.hexdigest())
    } else {
        None
    };
    let artwork_sha256 = if artwork_count > 0 {
        Some(hex_lower(&artwork_hasher.clone().finalize()))
    } else {
        None
    };

    let summary = match read_result {
        Err(_) => build_summary(
            &args,
            "error",
            Some("Timed out waiting for server disconnect"),
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            audio_chunk_count,
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            metadata_update_count,
            received_metadata,
            received_controller_state,
            sent_controller_command,
            artwork_stream,
            artwork_channel,
            artwork_count,
            artwork_sha256,
            artwork_byte_count,
        ),
        Ok(Err(reason)) => build_summary(
            &args,
            "error",
            Some(&reason),
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            audio_chunk_count,
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            metadata_update_count,
            received_metadata,
            received_controller_state,
            sent_controller_command,
            artwork_stream,
            artwork_channel,
            artwork_count,
            artwork_sha256,
            artwork_byte_count,
        ),
        Ok(Ok(())) if peer_hello.is_none() => build_summary(
            &args,
            "error",
            Some("Connection closed before handshake completed"),
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            audio_chunk_count,
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            metadata_update_count,
            received_metadata,
            received_controller_state,
            sent_controller_command,
            artwork_stream,
            artwork_channel,
            artwork_count,
            artwork_sha256,
            artwork_byte_count,
        ),
        Ok(Ok(())) => build_summary(
            &args,
            "ok",
            None,
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            audio_chunk_count,
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            metadata_update_count,
            received_metadata,
            received_controller_state,
            sent_controller_command,
            artwork_stream,
            artwork_channel,
            artwork_count,
            artwork_sha256,
            artwork_byte_count,
        ),
    };

    write_json(&args.summary, &summary)?;
    print!("{summary}");

    if summary.get("status").and_then(|value| value.as_str()) == Some("ok") {
        Ok(())
    } else {
        Err(summary
            .get("reason")
            .and_then(|value| value.as_str())
            .unwrap_or("adapter failed")
            .to_string())
    }
}

#[tokio::main]
async fn main() {
    let args = Args::parse();
    if let Err(reason) = run(args.clone()).await {
        eprintln!("{reason}");
        std::process::exit(1);
    }
}
