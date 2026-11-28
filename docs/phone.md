---
title: "LinKit All on your phone"
description: "Check runs, approve jobs and answer questions from your phone, anywhere. One QR code, no account, no app store. Your data stays on your PC."
---

# LinKit All on your phone

LinKit All runs on your PC. Your phone can open the same app from anywhere: at home, on mobile
data, or on another Wi-Fi. On the phone you can:

- start, pause and resume a run (**Home**);
- approve or reject jobs, answer questions and confirm submissions (**Needs you**);
- look through your best 200 jobs, or search all of them (**Jobs**), and see your results (**Home**);
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

1. On the PC, press **Remote control** on **Home**. Remote control turns on, and after a few
   seconds a QR code shows.
2. Scan it with your phone's camera.
    - **Android:** LinKit opens and pairs. Done.
    - **iPhone:** Safari asks you to add LinKit to the Home Screen: tap **Share > Add to Home
      Screen**, then open LinKit from the Home Screen. It pairs there. (An iPhone keeps a Home
      Screen app separate from Safari, so the pairing has to happen in the Home Screen app.)

The QR code works once, for 5 minutes. If it runs out, press **Show a new QR code**. The phone
stays paired until you unpair it.

In a terminal, `linkit rc` does the same without a browser tab: it starts LinKit All, turns on
remote control and prints the QR code in the terminal. Press Enter for a new code.

The PC must be on, awake, and running LinKit All. If it is not, the phone says
**PC not reachable** and connects again by itself when the PC is back.

## Notifications

On the phone, press **Remote control** on **Home** and tick **Notify me on this phone**. Allow
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

On the PC, press **Remote control** on **Home**, then **Unpair** next to the phone. It loses access
at once and stops getting notifications. A lost phone? Unpair it first.

To stop all phone access, press **Turn off remote control** there.

## How it works

- The tunnel is [iroh](https://iroh.computer): the phone finds your PC by its key, not by an
  address, and the connection is encrypted between the two of them.
- A phone browser cannot connect straight to a PC, so the encrypted traffic passes through a
  relay. By default these are n0's free public relays. A relay sees only encrypted data, never
  what is in it. If you run your own [iroh relay](https://docs.iroh.computer), enter it under
  **Remote control > Relay (advanced)**.
- Your PC only connects out. It opens no port, and LinKit runs no server.
- Each paired phone has its own key. The PC ties the phone's pairing to that key, so a copy of
  it is useless on any other device.
- No account, no subscription, no app store.

## Troubleshooting

| What you see | What to do |
|---|---|
| **PC not reachable** | Check that the PC is on and awake and LinKit All is running. |
| **Remote control** on the PC shows no QR code | The PC cannot reach a relay: check its internet connection. If you set your own relay, check its address. |
| The phone shows **Pair this phone** | It was unpaired, or the pairing link was already used. Show a new QR code on the PC. |
| iPhone: pairing does not finish in Safari | Add LinKit to the Home Screen first (Share > Add to Home Screen), then open it from there. |
| No **Notify me** switch on iPhone | Open LinKit from the Home Screen, not from Safari. |
| Notifications stopped | Press **Remote control** on the phone's **Home** and tick **Notify me** again. |
