const etb = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const two = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const one = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const money = (v: string | number) => `ETB ${etb.format(Number(v))}`;
export const dec2 = (v: string | number) => two.format(Number(v));
export const dec1 = (v: string | number) => one.format(Number(v));
export const qty = (v: string | number) => {
  const n = Number(v);
  return Number.isInteger(n) ? String(n) : two.format(n);
};
export const today = () => new Date().toISOString().slice(0, 10);

/** "3 roll" -> "3 rolls", "8 box" -> "8 boxes"; leaves 1 alone. */
export const plural = (n: string | number, word: string) => {
  if (Number(n) === 1 || word === "pcs" || word === "") return word;
  return /(s|x|z|ch|sh)$/.test(word) ? `${word}es` : `${word}s`;
};
