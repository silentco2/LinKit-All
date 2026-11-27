---
title: "LinKit All on your phone"
description: "Check runs, approve jobs and answer questions from your phone, anywhere, over your own private Tailscale network. Your data stays on your PC."
---

# LinKit All on your phone

LinKit All runs on your PC. Your phone can open the same app from anywhere: at home, on mobile
data, or on another Wi-Fi. On the phone you can:

- start, pause and resume a run (**Home**);
- approve or reject jobs, answer questions and confirm submissions (**Needs you**);
- look through your jobs (**Jobs**) and your results (**Report**);
- finish an application yourself with **Apply on this phone** (see below);
- get a notification when something needs you.

Your data never moves to the phone or to a server. The phone talks to your PC over your own
private [Tailscale](https://tailscale.com) network, an encrypted network between your own
devices. LinKit All runs no relay server and opens no port to the internet.

The phone cannot do everything the PC can. It cannot read your saved passwords (the vault),
see the LinKit Fill pairing code, export or back up your data, change your AI or API keys, change
your email settings, or turn on *Submit without asking me first*. Do those on the PC.

## What you need

- LinKit All on your PC, open (`linkit` running). The PC must be on and awake.
- A free Tailscale account.
- An Android phone (Chrome) or an iPhone (Safari, iOS 16.4 or newer for notifications).

## Set up Tailscale (once)

1. Install Tailscale on your PC from [tailscale.com/download](https://tailscale.com/download) and sign in.
2. Install the Tailscale app on your phone and sign in with the **same** account.
3. In the Tailscale admin console, open **DNS** and make sure **MagicDNS** and
   **HTTPS Certificates** are turned on.
4. On the PC, open a terminal and run:

    ```powershell
    tailscale serve --bg 8765
    ```

    It prints an address like `https://my-pc.tail1234.ts.net`. That is your PC's private
    address. Only devices signed in to your Tailscale account can open it.

    Using another port with `linkit serve --port`? Put that number instead of 8765.

## Turn on phone access and pair your phone

1. On the PC, open **Settings > Phone**.
2. Tick **Let my phone reach LinKit All**. The address is usually filled in for you. If it is
   empty, paste the address `tailscale serve` printed, for example `my-pc.tail1234.ts.net`.
   Press **Save**.
3. Press **Show the QR code**.
4. Scan the QR code with your phone's camera. LinKit All opens on the phone at **Pair this
   phone**. Check the name and press **Pair**.

The code works once, for 5 minutes. If it runs out, show a new one. After 5 wrong codes in a
minute, pairing pauses for a minute.

The phone stays paired until you unpair it. Only a phone left unused for over a year has to
pair again.

### Add it to your home screen

- **Android (Chrome):** menu **⋮ > Add to Home screen** (or **Install app**).
- **iPhone (Safari):** **Share > Add to Home Screen**. Notifications on iPhone only work from
  the home-screen app.

If the PC is off, asleep or out of reach, the app says **PC not reachable**. Nothing on the
phone is lost. It connects again when the PC is back.

## Notifications

On the phone, open **Settings > Phone** and tick **Notify me on this phone**. Allow
notifications when the phone asks.

You get a notification when more things wait for you after a step of a run ends. This is the
same moment the desktop notification would show. It says only **LinKit needs you (3)**. No
job, company or anything about you is ever in the message, because push messages pass through
Google's, Apple's or Mozilla's push service on the way to your phone. Tap it to open **Needs you**.

## Apply on this phone

Some applications have to be finished by you, for example on LinkedIn, Indeed and Glassdoor,
or where the app got stuck. On those cards in **Needs you**, and on a job's page in **Jobs**,
press **Apply on this phone**:

- **Open the application** opens the job's page.
- Each answer (your name, email, phone, links and what LinKit All already filled in) has a
  **Copy** button. Paste it into the form.
- **Share my CV** hands the CV PDF (the tailored one, if there is one) to the phone's share
  sheet, so you can attach it.

LinKit All never fills in forms on the phone. When you have sent it, press **I applied**.

## Unpair a phone

On the PC, open **Settings > Phone** and press **Unpair** next to the phone. It loses access
at once and stops getting notifications. A lost phone? Unpair it first.

To stop all phone access, untick **Let my phone reach LinKit All**. To close the address
itself, run `tailscale serve --https=443 off` on the PC.

## Same Wi-Fi without Tailscale?

Not supported. Without HTTPS, phones refuse to install the app or show notifications, and the
app would be open to anyone on that Wi-Fi. Tailscale gives you HTTPS and keeps it private,
even at home.

## Troubleshooting

| What you see | What to do |
|---|---|
| **PC not reachable** | Check that the PC is on and awake, LinKit All is running, and Tailscale shows *Connected* on both devices. |
| The phone keeps showing **Pair this phone** | The phone was unpaired, or the pairing expired. Show a new QR code on the PC. |
| **Host not allowed** | Phone access is off, or the address in **Settings > Phone** does not match the one `tailscale serve` printed. |
| No **Notify me** switch on iPhone | Add LinKit All to the home screen and open it from there. |
| Notifications stopped | Open **Settings > Phone** on the phone and tick **Notify me** again. |
