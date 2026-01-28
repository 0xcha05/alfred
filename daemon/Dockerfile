FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install protoc
RUN apk add --no-cache protobuf protobuf-dev

# Copy go mod files
COPY go.mod go.sum* ./
RUN go mod download

# Copy source
COPY . .

# Build
RUN CGO_ENABLED=0 GOOS=linux go build -o /daemon cmd/daemon/main.go

# Runtime image
FROM alpine:3.19

RUN apk add --no-cache ca-certificates tmux

COPY --from=builder /daemon /daemon

EXPOSE 50052

ENTRYPOINT ["/daemon"]
