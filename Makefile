.PHONY: all proto prime daemon infra clean test

# Default target
all: proto

# Generate protobuf code for both Python and Go
proto:
	@echo "Generating protobuf code..."
	# Go
	cd daemon && protoc --go_out=. --go-grpc_out=. -I../proto ../proto/daemon.proto
	# Python
	cd prime && python -m grpc_tools.protoc -I../proto --python_out=app/grpc_gen --grpc_python_out=app/grpc_gen ../proto/daemon.proto
	@echo "Done!"

# Setup development environment
setup:
	@echo "Setting up development environment..."
	# Python
	cd prime && python -m venv venv && . venv/bin/activate && pip install -r requirements.txt
	# Go
	cd daemon && go mod download
	# Create directories
	mkdir -p prime/app/grpc_gen
	mkdir -p prime/certs daemon/certs
	# Copy env example
	cp -n .env.example prime/.env || true
	@echo "Done! Edit prime/.env with your settings."

# Start infrastructure (PostgreSQL, Redis)
infra:
	docker-compose up -d postgres redis

# Stop infrastructure
infra-down:
	docker-compose down

# Run Prime locally
prime:
	cd prime && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run daemon locally
daemon:
	cd daemon && go run cmd/daemon/main.go

# Generate self-signed TLS certificates for development
certs:
	@echo "Generating self-signed certificates..."
	mkdir -p certs
	openssl req -x509 -newkey rsa:4096 -keyout certs/server.key -out certs/server.crt \
		-days 365 -nodes -subj "/CN=localhost"
	cp certs/* prime/certs/ 2>/dev/null || mkdir -p prime/certs && cp certs/* prime/certs/
	cp certs/* daemon/certs/ 2>/dev/null || mkdir -p daemon/certs && cp certs/* daemon/certs/
	@echo "Certificates generated in certs/"

# Run tests
test:
	cd prime && python -m pytest
	cd daemon && go test ./...

# Clean generated files
clean:
	rm -rf prime/app/grpc_gen/*.py
	rm -rf daemon/pkg/proto/*.go
	rm -rf certs/
	rm -rf prime/certs/ daemon/certs/

# Format code
fmt:
	cd prime && black app/
	cd daemon && go fmt ./...

# Lint
lint:
	cd prime && ruff check app/
	cd daemon && go vet ./...
