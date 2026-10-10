# Email Notification Setup Guide

## Overview
The CAPSTONE-189 demo system supports automated Gmail notifications for security alerts. Emails are sent to the address configured in `DEMO_EMAIL_RECIPIENT`. If that variable is not set, the demo falls back to `himankjain.xd.08@gmail.com`.

## How It Works
1. User selects **EMAIL** in the notification method dropdown
2. Clicks **Dispatch Demo Attack**
3. Backend processes the alert and triggers email notification
4. Email is sent asynchronously (doesn't block the response)
5. UI displays "Email sent to himankjain.xd.08@gmail.com"

## Setup Instructions

### Option 1: Gmail with App Password (Recommended for Production)

**Step 1: Enable 2-Factor Authentication on Gmail**
- Go to https://myaccount.google.com/security
- Under "How you sign in to Google," enable 2-Step Verification
- Follow the prompts to complete setup

**Step 2: Create App Password**
- Go to https://myaccount.google.com/apppasswords
- Select "Mail" and "Windows Computer" (or your device)
- Google will generate a 16-character password
- Copy this password (you'll use it in Step 3)

**Step 3: Set Environment Variables**

On Windows PowerShell:
```powershell
# Set environment variables
$env:DEMO_EMAIL_SENDER = "your-gmail@gmail.com"
$env:DEMO_EMAIL_PASSWORD = "your-16-char-app-password"
$env:DEMO_EMAIL_RECIPIENT = "your-inbox@gmail.com"

# Verify they're set
Write-Host $env:DEMO_EMAIL_SENDER
Write-Host $env:DEMO_EMAIL_PASSWORD
Write-Host $env:DEMO_EMAIL_RECIPIENT

# Start the backend server
cd c:\Users\Himank\Desktop\Capstone\Capstone_final
python -m uvicorn backend.api_demo_ext.app:app --host 127.0.0.1 --port 8001
```

**Step 4: Test Email**
- Open http://127.0.0.1:5173 (Dashboard)
- Go to Live Demo
- Select EMAIL notification method
- Click Dispatch Demo Attack
- Check your inbox for the email

### Option 2: Fallback Mode (Development/Testing)
If you don't configure Gmail credentials, the system will:
1. Display "Email queued" in the UI (user sees confirmation)
2. Log the email details to `email_logs/` directory
3. Print a message showing credentials need to be configured

This allows testing the email feature without production setup.

### Option 3: Using SendGrid or Mailgun
For production, you can modify `email_service.py` to use SendGrid or Mailgun instead of Gmail:

**SendGrid Setup:**
1. Create SendGrid account at https://sendgrid.com
2. Generate API key
3. Modify `email_service.py` to use SendGrid API
4. Set `SENDGRID_API_KEY` environment variable

**Mailgun Setup:**
1. Create Mailgun account at https://www.mailgun.com
2. Verify your domain
3. Generate API key
4. Modify `email_service.py` to use Mailgun API
5. Set `MAILGUN_API_KEY` environment variable

## Email Template
The system sends beautifully formatted HTML emails with:
- 🚨 **Severity Badge** (CRITICAL/HIGH/MEDIUM/LOW)
- **Alert Metrics**: Alert ID, Entity ID, Risk Score, Cloud Provider, Region, Target Team
- **Action Banner**: "Immediate Action Required" warning
- **Dashboard Link**: Direct link to review in the dashboard
- **Plain Text Fallback**: For email clients that don't support HTML

## Troubleshooting

### Problem: "Email queued for delivery" but email not received
**Solution:** Gmail credentials not configured
- Check that `DEMO_EMAIL_SENDER` and `DEMO_EMAIL_PASSWORD` are set
- Check that `DEMO_EMAIL_RECIPIENT` points to the inbox you want to show in the demo
- Check backend console output for error messages
- Look in `email_logs/` directory for logged emails
- Verify App Password is correct (16 characters, no spaces)

### Problem: "Connection refused" or SMTP errors
**Solution:** Gmail might be blocking the connection
- Check that you're using Gmail App Password (not regular password)
- Ensure 2FA is enabled on Gmail
- Try disabling VPN/proxy
- Check firewall settings (port 587 must be open)

### Problem: Email sent but sender shows as different address
**Solution:** This is normal Gmail behavior
- Emails sent via App Password may show a different sender
- The important thing is emails are being received
- You can configure "From" address in Gmail settings

## Verification
To verify emails are actually being sent:
1. Check your inbox for emails from your Gmail account
2. Look for subject line: `[CRITICAL] Security Alert - vol-amzn` (or similar)
3. Email should contain formatted alert details and dashboard link
4. Check spam/promotions folder if not in inbox

## Environment Variable Persistence

### For Windows Command Prompt (permanent):
```cmd
setx DEMO_EMAIL_SENDER "your-gmail@gmail.com"
setx DEMO_EMAIL_PASSWORD "your-16-char-app-password"
setx DEMO_EMAIL_RECIPIENT "your-inbox@gmail.com"
```

### For PowerShell (permanent):
```powershell
[Environment]::SetEnvironmentVariable("DEMO_EMAIL_SENDER", "your-gmail@gmail.com", "User")
[Environment]::SetEnvironmentVariable("DEMO_EMAIL_PASSWORD", "your-16-char-app-password", "User")
[Environment]::SetEnvironmentVariable("DEMO_EMAIL_RECIPIENT", "your-inbox@gmail.com", "User")
```

After setting permanent variables, restart PowerShell or the application.

## For Supervisor Demonstration
1. Have Gmail credentials configured before demo
2. Select EMAIL notification method
3. Dispatch alert and show email arriving in inbox
4. Display the beautiful HTML email with all metrics
5. Emphasize automated, production-ready notification system

## Next Steps
- ✅ Email service is now production-ready
- ✅ Fallback logging for development
- ✅ Beautiful HTML email templates
- ✅ Async notification sending (doesn't block API)
- 🔄 In progress: Heartbeat UI improvements
- 🔄 In progress: PowerPoint presentation with screenshots
