// Pre-fill link for the student-facing "Report interview date" Tally form
// (form nGyGj2). The team copies this and sends it to a student so they can
// report / update their interview date with their details already filled in.
// Matches the format the dashboard's existing "Report interview date" link uses:
//   https://tally.so/r/nGyGj2?contactid=<id>&email=<e>&firstname=<f>&surename=<l>&submissiontype=New&speciality=<s>
// NB: Tally's field key is the misspelled "surename" - must match exactly.
export const TALLY_INTERVIEW_FORM_SLUG = "nGyGj2";

export function tallyPrefillUrl({ contactId, first, last, email, speciality } = {}) {
  const params = new URLSearchParams();
  if (contactId) params.set("contactid", String(contactId));
  if (email) params.set("email", String(email).trim());
  if (first) params.set("firstname", String(first).trim());
  if (last) params.set("surename", String(last).trim());
  params.set("submissiontype", "New");
  params.set("speciality", speciality ? String(speciality).trim() : "");
  return `https://tally.so/r/${TALLY_INTERVIEW_FORM_SLUG}?${params.toString()}`;
}
