/**
 * Scroll to the element with this id, open the collapsed group around it and focus it if it is a control. Settings draws its
 * fields after the saved values arrive, so this looks again for about two seconds. Used for `/settings/jobs#exc`.
 */
export function focusFragment(id: string | null, tries = 40): void {
  if (!id) return;
  const el = document.getElementById(id);
  if (!el) {
    if (tries > 0) setTimeout(() => focusFragment(id, tries - 1), 50);
    return;
  }
  el.closest('details')?.setAttribute('open', '');
  el.scrollIntoView({ block: 'center' });
  if (/^(input|select|textarea|button)$/i.test(el.tagName)) el.focus({ preventScroll: true });
  else {
    el.classList.add('ring-2', 'ring-brand-500', 'rounded-lg');
    setTimeout(() => el.classList.remove('ring-2', 'ring-brand-500', 'rounded-lg'), 2500);
  }
}
