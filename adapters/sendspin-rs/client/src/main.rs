use clap::Parser;
use futures_util::{SinkExt, StreamExt};
use sendspin::protocol::client::AudioChunk;
use sendspin::protocol::messages::{
    AudioFormatSpec, ClientHello, ClientState, ClientTime, DeviceInfo, Message, PlayerState,
    PlayerSyncState, PlayerV1Support, ServerHello, StreamPlayerConfig,
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

fn build_summary(
    args: &Args,
    status: &str,
    reason: Option<&str>,
    peer_hello: Option<serde_json::Value>,
    server_hello: Option<&ServerHello>,
    stream: Option<&StreamPlayerConfig>,
    received_encoded_sha256: Option<String>,
    received_pcm_sha256: Option<String>,
    sample_count: usize,
    chunk_count: usize,
) -> serde_json::Value {
    serde_json::json!({
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
        "stream": stream.map(stream_json),
        "audio": {
            "audio_chunk_count": chunk_count,
            "received_encoded_sha256": received_encoded_sha256,
            "received_pcm_sha256": received_pcm_sha256,
            "received_sample_count": sample_count,
        }
    })
}

fn stream_json(stream: &StreamPlayerConfig) -> serde_json::Value {
    serde_json::json!({
        "codec": stream.codec,
        "sample_rate": stream.sample_rate,
        "channels": stream.channels,
        "bit_depth": stream.bit_depth,
        "codec_header": stream.codec_header,
    })
}

fn current_micros() -> i64 {
    static PROCESS_START: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();
    let start = PROCESS_START.get_or_init(Instant::now);
    start.elapsed().as_micros() as i64
}

async fn wait_for_server_url(registry_path: &Path, server_name: &str, timeout_s: f64) -> Result<String, String> {
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

async fn run(args: Args) -> Result<(), String> {
    if args.initiator_role != "client" {
        let summary = build_summary(
            &args,
            "error",
            Some("sendspin-rs client adapter only supports client-initiated scenarios"),
            None,
            None,
            None,
            None,
            None,
            0,
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

    let hello = Message::ClientHello(ClientHello {
        client_id: args.client_id.clone(),
        name: args.client_name.clone(),
        version: 1,
        supported_roles: vec!["player@v1".to_string()],
        device_info: Some(DeviceInfo {
            product_name: Some("sendspin-rs Conformance Client".to_string()),
            manufacturer: Some("Sendspin Conformance".to_string()),
            software_version: Some("0.1.0".to_string()),
        }),
        player_v1_support: Some(PlayerV1Support {
            supported_formats: vec![AudioFormatSpec {
                codec: "pcm".to_string(),
                channels: 1,
                sample_rate: 8000,
                bit_depth: 16,
            }],
            buffer_capacity: 2_000_000,
            supported_commands: vec!["volume".to_string(), "mute".to_string()],
        }),
        artwork_v1_support: None,
        visualizer_v1_support: None,
    });
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
    let mut chunk_count = 0usize;
    let mut saw_stream_end = false;
    let timeout = Duration::from_secs_f64(args.timeout_seconds);
    let mut sent_initial_state = false;

    let read_result = tokio::time::timeout(timeout, async {
        loop {
            let Some(frame) = read.next().await else {
                break;
            };

            match frame.map_err(|err| err.to_string())? {
                WsMessage::Text(text) => {
                    let raw_value = serde_json::from_str::<serde_json::Value>(&text)
                        .map_err(|err| err.to_string())?;
                    let message =
                        serde_json::from_str::<Message>(&text).map_err(|err| err.to_string())?;
                    match message {
                        Message::ServerHello(server_hello) => {
                            peer_hello = Some(raw_value);
                            server_hello_payload = Some(server_hello);
                            if !sent_initial_state {
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
                                sent_initial_state = true;
                            }
                        }
                        Message::StreamStart(stream_start) => {
                            current_stream = stream_start.player;
                        }
                        Message::StreamEnd(_) => {
                            saw_stream_end = true;
                            break;
                        }
                        Message::ServerTime(_)
                        | Message::GroupUpdate(_)
                        | Message::ServerState(_)
                        | Message::ServerCommand(_)
                        | Message::StreamClear(_) => {}
                        other => {
                            return Err(format!("Unexpected server message: {other:?}"));
                        }
                    }
                }
                WsMessage::Binary(data) => {
                    let stream = current_stream
                        .as_ref()
                        .ok_or_else(|| "Received audio before stream/start".to_string())?;
                    if stream.codec != "pcm" {
                        return Err(format!("Unsupported codec for second scenario: {}", stream.codec));
                    }
                    let chunk = AudioChunk::from_bytes(&data).map_err(|err| err.to_string())?;
                    encoded_hasher.update(&*chunk.data);
                    received_hasher
                        .update_from_pcm_bytes(&chunk.data, stream.bit_depth)
                        .map_err(|err| err.to_string())?;
                    chunk_count += 1;
                }
                WsMessage::Ping(payload) => {
                    write
                        .send(WsMessage::Pong(payload))
                        .await
                        .map_err(|err| err.to_string())?;
                }
                WsMessage::Close(_) => {
                    break;
                }
                _ => {}
            }
        }
        Ok::<(), String>(())
    })
    .await;

    let received_encoded_sha256 = if chunk_count > 0 {
        Some(hex_lower(&encoded_hasher.clone().finalize()))
    } else {
        None
    };
    let received_pcm_sha256 = if received_hasher.sample_count > 0 {
        Some(received_hasher.hexdigest())
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
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            chunk_count,
        ),
        Ok(Err(reason)) => build_summary(
            &args,
            "error",
            Some(&reason),
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            chunk_count,
        ),
        Ok(Ok(())) if peer_hello.is_none() => build_summary(
            &args,
            "error",
            Some("Connection closed before handshake completed"),
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            chunk_count,
        ),
        Ok(Ok(())) => build_summary(
            &args,
            "ok",
            if saw_stream_end { Some("stream_end") } else { None },
            peer_hello,
            server_hello_payload.as_ref(),
            current_stream.as_ref(),
            received_encoded_sha256,
            received_pcm_sha256,
            received_hasher.sample_count,
            chunk_count,
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
