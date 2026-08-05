param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId
)

$ErrorActionPreference = "Stop"

function Set-GoogleSecret {
    param(
        [string]$Name,
        [string]$Prompt
    )

    $secureValue = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        & gcloud secrets describe $Name --project=$ProjectId 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & gcloud secrets create $Name --project=$ProjectId --replication-policy=automatic
        }
        $value | & gcloud secrets versions add $Name --project=$ProjectId --data-file=-
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to add a version for secret $Name."
        }
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $value = $null
    }
}

Set-GoogleSecret "stock-screener-email-enabled" "EMAIL_ENABLED (True)"
Set-GoogleSecret "stock-screener-email-delivery-method" "EMAIL_DELIVERY_METHOD (GMAIL_API)"
Set-GoogleSecret "stock-screener-email-sender" "EMAIL_SENDER"
Set-GoogleSecret "stock-screener-email-receiver" "EMAIL_RECEIVER (comma-separated if needed)"
Set-GoogleSecret "stock-screener-gmail-client-id" "GMAIL_CLIENT_ID"
Set-GoogleSecret "stock-screener-gmail-client-secret" "GMAIL_CLIENT_SECRET"
Set-GoogleSecret "stock-screener-gmail-refresh-token" "GMAIL_REFRESH_TOKEN"
Set-GoogleSecret "stock-screener-attach-csv" "ATTACH_CSV (True)"
Set-GoogleSecret "stock-screener-attach-pdf" "ATTACH_PDF (True)"
