#!/bin/bash
# Generate protobuf code for Go and Python

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Generating protobuf code..."

# Go
echo "  Go..."
cd "$PROJECT_ROOT/daemon"
mkdir -p pkg/proto
protoc \
    --go_out=pkg/proto --go_opt=paths=source_relative \
    --go-grpc_out=pkg/proto --go-grpc_opt=paths=source_relative \
    -I"$PROJECT_ROOT/proto" \
    "$PROJECT_ROOT/proto/daemon.proto"

# Python
echo "  Python..."
cd "$PROJECT_ROOT/prime"
mkdir -p app/grpc_gen
python -m grpc_tools.protoc \
    -I"$PROJECT_ROOT/proto" \
    --python_out=app/grpc_gen \
    --grpc_python_out=app/grpc_gen \
    "$PROJECT_ROOT/proto/daemon.proto"

# Fix Python imports (grpc_tools generates incorrect relative imports)
cd "$PROJECT_ROOT/prime/app/grpc_gen"
if [ -f daemon_pb2_grpc.py ]; then
    sed -i.bak 's/import daemon_pb2/from . import daemon_pb2/' daemon_pb2_grpc.py
    rm -f daemon_pb2_grpc.py.bak
fi

echo "Done!"
