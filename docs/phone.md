---
title: "LinKit All on your phone"
description: "Check runs, approve jobs and answer questions from your phone, anywhere. One QR code, no account, no app store. Your data stays on your PC."
---

# LinKit All on your phone

LinKit All runs on your PC. Your phone can open the same app from anywhere: at home, on mobile
data, or on another Wi-Fi. On the phone you can:

- start, pause and resume a run (**Home**);
- approve or reject jobs, answer questions and confirm submissions (**Needs you**);
- look through your jobs (**Jobs**) and your results (**Report**);
- finish an application yourself with **Apply on this phone** (see below);
- get a notification when something needs you.

There is nothing to install or sign up for. The phone app is a web page,
`linkit-all.github.io/app/`, that talks to **your PC directly** through an encrypted tunnel.
Your data never moves to a server: the page is only the app's code, and everything it shows
comes from your PC, encrypted end to end.

The phone cannot do everything the PC can. It cannot read your saved passwords (the vault),
see the LinKit Fill pairing code, export or back up your data, change your AI or API keys, change
your email settings, or turn on *Submit without asking me first*. Do those on the PC.

## Pair your phone (once)

1. On the PC, open **Settings > Phone** and tick **Let my phone reach LinKit All**. After a few
   seconds it says **Ready**.
2. Press **Show the QR code**.
3. Scan it with your phone's camera.
    - **Android:** LinKit opens and pairs. Done.
    - **iPhone:** Safari asks you to add LinKit to the Home Screen: tap **Share > Add to Home
      Screen**, then open LinKit from the Home Screen. It pairs there. (An iPhone keeps a Home
      Screen app separate from Safari, so the pairing has to happen in the Home Screen app.)

The QR code works once, for 5 minutes. If it runs out, show a new one. The phone stays paired
until you unpair it.

The PC must be on, awake, and running LinKit All. If it is not, the phone says
**PC not reachable** and connects again by itself when the PC is back.

## Notifications

On the phone, open **Settings > Phone** and tick **Notify me on this phone**. Allow
notifications when the phone asks. On iPhone this works in the Home Screen app.

You get a notification when more things wait for you after a step of a run ends, the same moment
the desktop notification would show. It says only **LinKit needs you (3)**. No job, company or
anything about you is ever in the message, because push messages pass through Google's, Apple's
or Mozilla's push service on the way to your phone. Tap it to open **Needs you**.

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

To stop all phone access, untick **Let my phone reach LinKit All**.

## How it works

- The tunnel is [iroh](https://iroh.computer): the phone finds your PC by its key, not by an
  address, and the connection is encrypted between the two of them.
- A phone browser cannot connect straight to a PC, so the encrypted traffic passes through a
  relay. By default these are n0's free public relays. A relay sees only encrypted data, never
  what is in it. If you run your own [iroh relay](https://docs.iroh.computer), enter it under
  **Settings > Phone > Relay (advanced)**.
- Your PC only connects out. It opens no port, and LinKit runs no server.
- Each paired phone has its own key. The PC ties the phone's pairing to that key, so a copy of
  it is useless on any other device.
- No account, no subscription, no app store.

## Troubleshooting

| What you see | What to do |
|---|---|
| **PC not reachable** | Check that the PC is on and awake and LinKit All is running. |
| **Settings > Phone** on the PC does not say **Ready** | The PC cannot reach a relay: check its internet connection. If you set your own relay, check its address. |
| The phone shows **Pair this phone** | It was unpaired, or the pairing link was already used. Show a new QR code on the PC. |
| iPhone: pairing does not finish in Safari | Add LinKit to the Home Screen first (Share > Add to Home Screen), then open it from there. |
| No **Notify me** switch on iPhone | Open LinKit from the Home Screen, not from Safari. |
| Notifications stopped | Open **Settings > Phone** on the phone and tick **Notify me** again. |
