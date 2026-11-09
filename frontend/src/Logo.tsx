const base = import.meta.env.BASE_URL;

/** The company logo; a light version of the line work is swapped in on dark screens. */
export default function Logo({ height = 38 }: { height?: number }) {
  return (
    <>
      <img className="logo logo-light" src={`${base}logo.png`} alt="Betewubet logo" style={{ height }} />
      <img className="logo logo-dark" src={`${base}logo-dark.png`} alt="Betewubet logo" style={{ height }} />
    </>
  );
}
