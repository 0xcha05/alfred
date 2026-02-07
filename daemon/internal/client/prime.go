package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// PrimeClient handles communication with Ultron Prime
type PrimeClient struct {
	baseURL         string
	registrationKey string
	httpClient      *http.Client
	daemonID        string
}

// RegistrationRequest is sent to Prime to register this daemon
type RegistrationRequest struct {
	Name         string   `json:"name"`
	Hostname     string   `json:"hostname"`
	Capabilities []string `json:"capabilities"`
	GRPCAddress  string   `json:"grpc_address"`
	IsSoulDaemon bool     `json:"is_soul_daemon"`
	UltronRoot   string   `json:"ultron_root,omitempty"`
}

// RegistrationResponse is received from Prime after registration
type RegistrationResponse struct {
	DaemonID string `json:"daemon_id"`
	Message  string `json:"message"`
}

// NewPrimeClient creates a new client for communicating with Prime
func NewPrimeClient(baseURL, registrationKey string) *PrimeClient {
	return &PrimeClient{
		baseURL:         baseURL,
		registrationKey: registrationKey,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// Register registers this daemon with Ultron Prime
func (c *PrimeClient) Register(ctx context.Context, req RegistrationRequest) (*RegistrationResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/api/daemon/register", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("X-Registration-Key", c.registrationKey)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registration failed: %s - %s", resp.Status, string(body))
	}

	var regResp RegistrationResponse
	if err := json.NewDecoder(resp.Body).Decode(&regResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	c.daemonID = regResp.DaemonID
	return &regResp, nil
}

// Heartbeat sends a heartbeat to Prime
func (c *PrimeClient) Heartbeat(ctx context.Context) error {
	if c.daemonID == "" {
		return fmt.Errorf("not registered with Prime")
	}

	url := fmt.Sprintf("%s/api/daemon/%s/heartbeat", c.baseURL, c.daemonID)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("X-Registration-Key", c.registrationKey)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("failed to send heartbeat: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("heartbeat failed: %s - %s", resp.Status, string(body))
	}

	return nil
}

// GetDaemonID returns the daemon ID assigned by Prime
func (c *PrimeClient) GetDaemonID() string {
	return c.daemonID
}

// IsRegistered returns true if registered with Prime
func (c *PrimeClient) IsRegistered() bool {
	return c.daemonID != ""
}
