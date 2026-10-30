// A text cell a spreadsheet would run as a formula (= + - @, or a leading tab
// or CR) gets a leading quote. Numbers are left alone, negative ones included,
// and so is a string that is only a number.
const FORMULA_START = /^[=+\-@\t\r]/;
const PLAIN_NUMBER = /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i;

/**
 * RFC 4180 escaping, plus formula neutralising.
 *
 * Company names in this universe contain commas and the occasional quote, and
 * gate-failure strings contain both. A naive join would shift every later
 * column on those rows.
 */
export function csvCell(value) {
  if (value === null || value === undefined) return "";
  let text = String(value);
  if (typeof value === "string" && FORMULA_START.test(text) && !PLAIN_NUMBER.test(text)) {
    text = `'${text}`;
  }
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}
