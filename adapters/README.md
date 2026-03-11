# Adapter Contract

Every implementation in the matrix is modeled as two CLIs:

- `server`: starts first, discovers or looks up a target client, connects, streams the fixture, writes a JSON summary, exits `0` on success
- `client`: starts second, advertises or listens for server-initiated connections, receives audio, writes a JSON summary, exits `0` on success

Current checked-in adapters:

- `src/conformance/adapters/aiosendspin_server.py`: real Python server adapter
- `src/conformance/adapters/aiosendspin_client.py`: real Python client adapter
- `adapters/sendspin-dotnet/client/`: real `.NET` client adapter source

Current placeholders in the matrix are modeled in `src/conformance/implementations.py` with explicit skip reasons until those repositories expose the listener/server behavior required by the first scenario.
