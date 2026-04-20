# Adapter Contract

Every implementation in the matrix is modeled as two CLIs:

- `server`: starts first, either discovers/connects to a target client or advertises its own endpoint for a client-initiated scenario, streams the fixture, writes a JSON summary, exits `0` on success
- `client`: starts second, either listens for a server-initiated connection or discovers/connects to a server for a client-initiated scenario, receives audio, writes a JSON summary, exits `0` on success

Current checked-in adapters:

- `src/conformance/adapters/aiosendspin_server.py`: real Python server adapter
- `src/conformance/adapters/aiosendspin_client.py`: real Python client adapter
- `adapters/sendspin-dotnet/client/`: real `.NET` client adapter source for client-initiated PCM plus the server-initiated PCM, metadata, artwork, controller, and FLAC scenarios
- `adapters/sendspin-go/`: real Go adapter source for the current client/server scenario set
- `adapters/SendspinKit/client/`: real Swift client adapter source for client-initiated PCM plus the server-initiated PCM, metadata, artwork, controller, and FLAC scenarios
- `adapters/sendspin-js/client.mjs`: real Node.js client adapter for client-initiated PCM plus the server-initiated PCM, metadata, and controller scenarios, driving the public `SendspinCore` SDK over an adapter-owned WebSocket
- `adapters/sendspin-rs/client/`: real Rust client adapter source for client-initiated PCM plus the server-initiated PCM, metadata, artwork, controller, and FLAC scenarios
- `src/conformance/adapters/placeholder.py`: fail-fast placeholder for unsupported roles

Current placeholders in the matrix are modeled in `src/conformance/implementations.py` and fail immediately with a summary explaining why the role is unavailable for a scenario.
