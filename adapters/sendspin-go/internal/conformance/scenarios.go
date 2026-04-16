package conformance

import "strings"

const (
	VerificationModeAudioPCM      = "audio-pcm"
	VerificationModeAudioEncoded  = "audio-encoded-bytes"
	VerificationModeMetadata      = "metadata"
	VerificationModeController    = "controller"
	VerificationModeArtwork       = "artwork"
)

func SupportsMode(mode string) bool {
	return IsPlayerMode(mode) ||
		IsMetadataMode(mode) ||
		IsControllerMode(mode) ||
		IsArtworkMode(mode)
}

func IsPlayerMode(mode string) bool {
	return mode == VerificationModeAudioPCM || mode == VerificationModeAudioEncoded
}

func IsMetadataMode(mode string) bool {
	return mode == VerificationModeMetadata
}

func IsControllerMode(mode string) bool {
	return mode == VerificationModeController
}

func IsArtworkMode(mode string) bool {
	return mode == VerificationModeArtwork
}

func NormalizeArtworkFormat(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "png":
		return "png"
	case "bmp":
		return "bmp"
	default:
		return "jpeg"
	}
}

func BuildReadyPayload(scenarioID string, initiatorRole string, url string) map[string]any {
	payload := map[string]any{
		"status":         "ready",
		"scenario_id":    scenarioID,
		"initiator_role": initiatorRole,
	}
	if url != "" {
		payload["url"] = url
	}
	return payload
}

func ActiveRoles(mode string, supported []string) []string {
	families := map[string]bool{}
	switch {
	case IsPlayerMode(mode):
		families["player"] = true
		families["metadata"] = true
	case IsMetadataMode(mode):
		families["metadata"] = true
	case IsControllerMode(mode):
		families["controller"] = true
	case IsArtworkMode(mode):
		families["artwork"] = true
	}

	roles := make([]string, 0, len(supported))
	seen := map[string]bool{}
	for _, role := range supported {
		family := role
		if index := strings.Index(role, "@"); index > 0 {
			family = role[:index]
		}
		if families[family] && !seen[family] {
			roles = append(roles, role)
			seen[family] = true
		}
	}
	return roles
}
