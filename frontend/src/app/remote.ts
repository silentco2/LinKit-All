/** True on a paired phone reaching the PC over the tailnet (docs/phone.md); false on the PC itself. */
export const REMOTE = !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
