$ErrorActionPreference = "Stop"

$rules = @(
    @{ Name = "RoS Emulator HTTP"; Port = 80; Protocol = "TCP" },
    @{ Name = "RoS Emulator HTTPS"; Port = 443; Protocol = "TCP" },
    @{ Name = "RoS Emulator LoginApp"; Port = 20013; Protocol = "UDP" },
    @{ Name = "RoS Emulator BaseApp"; Port = 20015; Protocol = "UDP" }
)

foreach ($rule in $rules) {
    if (-not (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule `
            -DisplayName $rule.Name `
            -Direction Inbound `
            -Action Allow `
            -Protocol $rule.Protocol `
            -LocalPort $rule.Port `
            -Profile Domain,Private,Public | Out-Null
    }
}

Get-NetFirewallRule -DisplayName "RoS Emulator *" |
    Get-NetFirewallPortFilter |
    Format-Table Protocol, LocalPort -AutoSize
