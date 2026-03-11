using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Sendspin.SDK.Audio;
using Sendspin.SDK.Client;
using Sendspin.SDK.Connection;
using Sendspin.SDK.Models;
using Sendspin.SDK.Protocol;
using Sendspin.SDK.Protocol.Messages;
using Sendspin.SDK.Synchronization;

var options = CliOptions.Parse(args);
var jsonOptions = new JsonSerializerOptions
{
    WriteIndented = true,
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
};
using var loggerFactory = LoggerFactory.Create(builder =>
{
    builder.AddSimpleConsole(console =>
    {
        console.SingleLine = true;
        console.TimestampFormat = "HH:mm:ss ";
    });
    builder.SetMinimumLevel(ParseLogLevel(options.LogLevel));
});

var pipeline = new HashingAudioPipeline(loggerFactory);
var disconnectTcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
ConnectionSnapshot? connectedServer = null;
string? failureReason = null;
JsonElement? peerHello = null;

if (options.ScenarioId == "client-initiated-pcm")
{
    await RunOutboundClientAsync();
}
else
{
    await RunListenerClientAsync();
}

if (connectedServer is null)
{
    failureReason ??= "Connection closed before handshake completed";
}

var summary = new
{
    status = failureReason is null ? "ok" : "error",
    reason = failureReason,
    implementation = "sendspin-dotnet",
    role = "client",
    scenario_id = options.ScenarioId,
    preferred_codec = options.PreferredCodec,
    client_name = options.ClientName,
    client_id = options.ClientId,
    server = connectedServer,
    peer_hello = peerHello,
    audio = pipeline.Snapshot(),
};
WriteJson(options.Summary, summary);
Console.WriteLine(JsonSerializer.Serialize(summary, jsonOptions));
return failureReason is null ? 0 : 1;

async Task RunListenerClientAsync()
{
    var listener = new SendspinListener(
        loggerFactory.CreateLogger<SendspinListener>(),
        new ListenerOptions
        {
            Port = options.Port,
            Path = options.Path,
        });

    listener.ServerConnected += (_, socket) =>
    {
        _ = HandleIncomingConnectionAsync(socket);
    };

    await listener.StartAsync();
    try
    {
        WriteRegistry(options.Registry, options.ClientName, $"ws://127.0.0.1:{options.Port}{options.Path}");
        WriteJson(
            options.Ready,
            new
            {
                status = "ready",
                scenario_id = options.ScenarioId,
                url = $"ws://127.0.0.1:{options.Port}{options.Path}",
            });

        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(options.TimeoutSeconds));
        await disconnectTcs.Task.WaitAsync(timeout.Token);
    }
    catch (OperationCanceledException)
    {
        failureReason ??= "Timed out waiting for server disconnect";
    }
    finally
    {
        await listener.StopAsync();
    }
}

async Task RunOutboundClientAsync()
{
    WriteJson(
        options.Ready,
        new
        {
            status = "ready",
            scenario_id = options.ScenarioId,
        });

    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(options.TimeoutSeconds));
    try
    {
        var serverUrl = await WaitForRegistryAsync(options.Registry, options.ServerName, timeout.Token);
        var capabilities = BuildCapabilities(options);
        await using var connection = new SendspinConnection(
            loggerFactory.CreateLogger<SendspinConnection>(),
            new ConnectionOptions
            {
                AutoReconnect = false,
            });
        connection.TextMessageReceived += (_, text) => CapturePeerHello(text);

        using var client = new SendspinClientService(
            loggerFactory.CreateLogger<SendspinClientService>(),
            connection,
            new KalmanClockSynchronizer(loggerFactory.CreateLogger<KalmanClockSynchronizer>()),
            capabilities,
            pipeline);

        client.ConnectionStateChanged += (_, state) =>
        {
            if (state.NewState == ConnectionState.Disconnected)
            {
                disconnectTcs.TrySetResult(true);
            }
        };

        await client.ConnectAsync(new Uri(serverUrl), timeout.Token);
        connectedServer = new ConnectionSnapshot(
            client.ServerId ?? "unknown",
            client.ServerName ?? "unknown",
            client.ConnectionReason);

        await disconnectTcs.Task.WaitAsync(timeout.Token);
    }
    catch (OperationCanceledException) when (timeout.IsCancellationRequested)
    {
        failureReason ??= "Timed out waiting for server disconnect";
    }
    catch (Exception ex)
    {
        failureReason ??= ex.Message;
    }
}

async Task HandleIncomingConnectionAsync(WebSocketClientConnection socket)
{
    try
    {
        var connection = new IncomingConnection(
            loggerFactory.CreateLogger<IncomingConnection>(),
            socket);
        var capabilities = BuildCapabilities(options);
        connection.TextMessageReceived += (_, text) => CapturePeerHello(text);

        var client = new SendspinClientService(
            loggerFactory.CreateLogger<SendspinClientService>(),
            connection,
            new KalmanClockSynchronizer(loggerFactory.CreateLogger<KalmanClockSynchronizer>()),
            capabilities,
            pipeline);

        client.ConnectionStateChanged += (_, state) =>
        {
            if (state.NewState == ConnectionState.Disconnected)
            {
                disconnectTcs.TrySetResult(true);
            }
        };

        client.GroupStateChanged += (_, _) => { };
        client.PlayerStateChanged += (_, _) => { };

        await connection.StartAsync();
        await SendClientHelloAsync(connection, capabilities);
        var handshakeOk = await WaitForHandshakeAsync(client, connection, TimeSpan.FromSeconds(10));
        if (!handshakeOk)
        {
            failureReason ??= "Handshake did not complete";
            disconnectTcs.TrySetResult(true);
            return;
        }

        connectedServer = new ConnectionSnapshot(
            client.ServerId ?? "unknown",
            client.ServerName ?? "unknown",
            client.ConnectionReason);
    }
    catch (Exception ex)
    {
        failureReason ??= ex.Message;
        disconnectTcs.TrySetResult(true);
    }
}

void CapturePeerHello(string text)
{
    try
    {
        if (MessageSerializer.GetMessageType(text) != MessageTypes.ServerHello)
        {
            return;
        }

        using var document = JsonDocument.Parse(text);
        peerHello = document.RootElement.Clone();
    }
    catch
    {
        // Keep the adapter resilient even if hello capture fails.
    }
}

async Task SendClientHelloAsync(IncomingConnection connection, ClientCapabilities capabilities)
{
    var hello = ClientHelloMessage.Create(
        clientId: capabilities.ClientId,
        name: capabilities.ClientName,
        supportedRoles: capabilities.Roles,
        playerSupport: new PlayerSupport
        {
            SupportedFormats = capabilities.AudioFormats
                .Select(format => new AudioFormatSpec
                {
                    Codec = format.Codec,
                    Channels = format.Channels,
                    SampleRate = format.SampleRate,
                    BitDepth = format.BitDepth ?? 16,
                })
                .ToList(),
            BufferCapacity = capabilities.BufferCapacity,
            SupportedCommands = new List<string> { "volume", "mute" },
        },
        artworkSupport: new ArtworkSupport
        {
            Channels = new List<ArtworkChannelSpec>
            {
                new()
                {
                    Source = "album",
                    Format = "jpeg",
                    MediaWidth = 256,
                    MediaHeight = 256,
                },
            },
        },
        deviceInfo: new DeviceInfo
        {
            ProductName = "Conformance Dotnet Client",
            Manufacturer = "Sendspin Conformance",
            SoftwareVersion = "0.1.0",
        });
    await connection.SendMessageAsync(hello);
}

async Task<string> WaitForRegistryAsync(string path, string serverName, CancellationToken cancellationToken)
{
    while (!cancellationToken.IsCancellationRequested)
    {
        var url = ReadRegistry(path, serverName);
        if (!string.IsNullOrWhiteSpace(url))
        {
            return url;
        }

        await Task.Delay(100, cancellationToken);
    }

    throw new OperationCanceledException(cancellationToken);
}

static string? ReadRegistry(string path, string name)
{
    if (!File.Exists(path))
    {
        return null;
    }

    var payload = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, string>>>(
        File.ReadAllText(path));
    if (payload is null || !payload.TryGetValue(name, out var entry))
    {
        return null;
    }

    return entry.TryGetValue("url", out var url) ? url : null;
}

static async Task<bool> WaitForHandshakeAsync(
    SendspinClientService client,
    IncomingConnection connection,
    TimeSpan timeout)
{
    var handshakeComplete = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

    void OnStateChanged(object? _, ConnectionStateChangedEventArgs state)
    {
        if (state.NewState == ConnectionState.Connected)
        {
            handshakeComplete.TrySetResult(true);
        }
        else if (state.NewState == ConnectionState.Disconnected)
        {
            handshakeComplete.TrySetResult(false);
        }
    }

    client.ConnectionStateChanged += OnStateChanged;
    using var cts = new CancellationTokenSource(timeout);
    try
    {
        return await handshakeComplete.Task.WaitAsync(cts.Token);
    }
    catch (OperationCanceledException)
    {
        await connection.DisconnectAsync("handshake_timeout");
        return false;
    }
    finally
    {
        client.ConnectionStateChanged -= OnStateChanged;
    }
}

static ClientCapabilities BuildCapabilities(CliOptions options)
{
    var audioFormats = options.PreferredCodec.Equals("pcm", StringComparison.OrdinalIgnoreCase)
        ? new List<AudioFormat>
        {
            new() { Codec = "pcm", SampleRate = 8000, Channels = 1, BitDepth = 16 },
        }
        : new List<AudioFormat>
        {
            new() { Codec = "flac", SampleRate = 8000, Channels = 1, BitDepth = 16 },
            new() { Codec = "pcm", SampleRate = 8000, Channels = 1, BitDepth = 16 },
            new() { Codec = "flac", SampleRate = 44100, Channels = 2, BitDepth = 16 },
            new() { Codec = "pcm", SampleRate = 44100, Channels = 2, BitDepth = 16 },
        };

    return new ClientCapabilities
    {
        ClientId = options.ClientId,
        ClientName = options.ClientName,
        Roles = new List<string> { "player@v1" },
        BufferCapacity = 2_000_000,
        AudioFormats = audioFormats,
        ArtworkFormats = new List<string> { "jpeg" },
        ArtworkMaxSize = 256,
        ProductName = "Conformance Dotnet Client",
        Manufacturer = "Sendspin Conformance",
        SoftwareVersion = "0.1.0",
    };
}

void WriteRegistry(string path, string clientName, string url)
{
    Dictionary<string, Dictionary<string, string>> payload = new();
    if (File.Exists(path))
    {
        payload = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, string>>>(
            File.ReadAllText(path),
            jsonOptions) ?? new();
    }

    payload[clientName] = new Dictionary<string, string> { ["url"] = url };
    WriteJson(path, payload);
}

void WriteJson(string path, object payload)
{
    var directory = Path.GetDirectoryName(path);
    if (!string.IsNullOrEmpty(directory))
    {
        Directory.CreateDirectory(directory);
    }

    File.WriteAllText(path, JsonSerializer.Serialize(payload, jsonOptions) + Environment.NewLine);
}

static LogLevel ParseLogLevel(string value) =>
    value.ToUpperInvariant() switch
    {
        "TRACE" => LogLevel.Trace,
        "DEBUG" => LogLevel.Debug,
        "WARNING" => LogLevel.Warning,
        "ERROR" => LogLevel.Error,
        _ => LogLevel.Information,
    };

internal sealed record ConnectionSnapshot(string ServerId, string ServerName, string? ConnectionReason);

internal sealed class CliOptions
{
    public required string ClientName { get; init; }
    public required string ClientId { get; init; }
    public required string Summary { get; init; }
    public required string Ready { get; init; }
    public required string Registry { get; init; }
    public required string ScenarioId { get; init; }
    public required string PreferredCodec { get; init; }
    public required string ServerName { get; init; }
    public required string ServerId { get; init; }
    public required double TimeoutSeconds { get; init; }
    public required int Port { get; init; }
    public required string Path { get; init; }
    public required string LogLevel { get; init; }

    public static CliOptions Parse(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index += 2)
        {
            if (!args[index].StartsWith("--", StringComparison.Ordinal))
            {
                throw new ArgumentException($"Unexpected argument: {args[index]}");
            }

            if (index + 1 >= args.Length)
            {
                throw new ArgumentException($"Missing value for {args[index]}");
            }

            values[args[index][2..]] = args[index + 1];
        }

        return new CliOptions
        {
            ClientName = Require(values, "client-name"),
            ClientId = Require(values, "client-id"),
            Summary = Require(values, "summary"),
            Ready = Require(values, "ready"),
            Registry = Require(values, "registry"),
            ScenarioId = values.GetValueOrDefault("scenario-id", "server-initiated-flac"),
            PreferredCodec = values.GetValueOrDefault("preferred-codec", "flac"),
            ServerName = values.GetValueOrDefault("server-name", "Sendspin Conformance Server"),
            ServerId = values.GetValueOrDefault("server-id", "conformance-server"),
            TimeoutSeconds = double.Parse(values.GetValueOrDefault("timeout-seconds", "30"), System.Globalization.CultureInfo.InvariantCulture),
            Port = int.Parse(values.GetValueOrDefault("port", "8928"), System.Globalization.CultureInfo.InvariantCulture),
            Path = values.GetValueOrDefault("path", "/sendspin"),
            LogLevel = values.GetValueOrDefault("log-level", "Information"),
        };
    }

    private static string Require(Dictionary<string, string> values, string key)
    {
        if (!values.TryGetValue(key, out var value) || string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"Missing required option --{key}");
        }
        return value;
    }
}

internal sealed class HashingAudioPipeline : IAudioPipeline
{
    private readonly AudioDecoderFactory _decoderFactory;
    private IAudioDecoder? _decoder;
    private float[] _decodeBuffer = Array.Empty<float>();
    private readonly MemoryStream _decodedFloatStream = new();
    private readonly MemoryStream _encodedStream = new();
    private int _audioChunkCount;

    public HashingAudioPipeline(ILoggerFactory loggerFactory)
    {
        _decoderFactory = new AudioDecoderFactory(loggerFactory);
    }

    public AudioPipelineState State { get; private set; } = AudioPipelineState.Idle;
    public bool IsReady => _decoder is not null;
    public AudioBufferStats? BufferStats => null;
    public AudioFormat? CurrentFormat { get; private set; }
    public AudioFormat? OutputFormat => CurrentFormat;
    public int DetectedOutputLatencyMs => 0;

    public event EventHandler<AudioPipelineState>? StateChanged;
    public event EventHandler<AudioPipelineError>? ErrorOccurred;

    public Task StartAsync(AudioFormat format, long? targetTimestamp = null, CancellationToken cancellationToken = default)
    {
        _decoder?.Dispose();
        _decoder = _decoderFactory.Create(format);
        _decodeBuffer = new float[_decoder.MaxSamplesPerFrame];
        CurrentFormat = format;
        SetState(AudioPipelineState.Buffering);
        return Task.CompletedTask;
    }

    public Task StopAsync()
    {
        _decoder?.Dispose();
        _decoder = null;
        SetState(AudioPipelineState.Idle);
        return Task.CompletedTask;
    }

    public void NotifyReconnect() { }

    public void Clear(long? newTargetTimestamp = null)
    {
        _decoder?.Reset();
    }

    public void ProcessAudioChunk(AudioChunk chunk)
    {
        if (_decoder is null)
        {
            return;
        }

        _encodedStream.Write(chunk.EncodedData, 0, chunk.EncodedData.Length);
        _audioChunkCount += 1;
        var decodedCount = _decoder.Decode(chunk.EncodedData, _decodeBuffer);
        if (decodedCount <= 0)
        {
            return;
        }

        var bytes = MemoryMarshal.AsBytes(_decodeBuffer.AsSpan(0, decodedCount));
        _decodedFloatStream.Write(bytes);
        SetState(AudioPipelineState.Playing);
    }

    public void SetVolume(int volume) { }

    public void SetMuted(bool muted) { }

    public Task SwitchDeviceAsync(string? deviceId, CancellationToken cancellationToken = default) =>
        Task.CompletedTask;

    public ValueTask DisposeAsync()
    {
        _decoder?.Dispose();
        _decodedFloatStream.Dispose();
        _encodedStream.Dispose();
        return ValueTask.CompletedTask;
    }

    public object Snapshot() => new
    {
        received_pcm_sha256 = ToHex(SHA256.HashData(_decodedFloatStream.ToArray())),
        received_encoded_sha256 = ToHex(SHA256.HashData(_encodedStream.ToArray())),
        received_sample_count = _decodedFloatStream.Length / sizeof(float),
        audio_chunk_count = _audioChunkCount,
    };

    private void SetState(AudioPipelineState state)
    {
        if (State == state)
        {
            return;
        }

        State = state;
        StateChanged?.Invoke(this, state);
    }

    private static string ToHex(byte[] bytes) =>
        Convert.ToHexString(bytes).ToLowerInvariant();
}
