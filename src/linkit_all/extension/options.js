const $ = (id) => document.getElementById(id);

chrome.storage.local.get('token').then(({ token = '' }) => {
  $('token').value = token;
});

$('save').addEventListener('click', async () => {
  await chrome.storage.local.set({ token: $('token').value.trim() });
  $('msg').textContent = 'Saved. Open a job from "Needs you" in LinKit All to fill it.';
});
