// Pre-fill link for the student-facing Tally form. The form reads three query
// params — first name, last name, email — so we can hand a student a link
// that's already filled in for them (e.g.
// https://tally.so/r/0Qr5py?name=Dalia&lastname=Ahmed&email=basibaa78@gmail.com).
export const TALLY_FORM_SLUG = "0Qr5py";

export function tallyPrefillUrl({ first, last, email } = {}) {
  const params = new URLSearchParams();
  if (first) params.set("name", String(first).trim());
  if (last) params.set("lastname", String(last).trim());
  if (email) params.set("email", String(email).trim());
  const qs = params.toString();
  return `https://tally.so/r/${TALLY_FORM_SLUG}${qs ? `?${qs}` : ""}`;
}
