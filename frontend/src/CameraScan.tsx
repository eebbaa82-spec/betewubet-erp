import { useEffect, useRef, useState } from "react";

// BarcodeDetector is built into Chrome on Android and some desktop browsers; it is not in TypeScript's DOM types yet.
type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };
type DetectorCtor = new (opts: { formats: string[] }) => Detector;
const ctor = () => (window as unknown as { BarcodeDetector?: DetectorCtor }).BarcodeDetector;

export const cameraSupported = () => !!ctor() && !!navigator.mediaDevices?.getUserMedia;

/** Reads one QR code with the device camera, then calls onCode and stops. */
export default function CameraScan({ onCode }: { onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const latest = useRef(onCode);
  latest.current = onCode; // the page re-renders every second; keep the camera running across renders
  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer = 0;
    let done = false;
    const Ctor = ctor();
    if (!Ctor) return;
    const detector = new Ctor({ formats: ["qr_code"] });
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then((s) => {
      stream = s;
      if (!video.current) return;
      video.current.srcObject = s;
      video.current.play().catch(() => undefined);
      const tick = async () => {
        if (done || !video.current) return;
        try {
          const found = await detector.detect(video.current);
          if (found[0]?.rawValue) { done = true; latest.current(found[0].rawValue); return; }
        } catch { /* frame not ready yet */ }
        timer = window.setTimeout(tick, 250);
      };
      tick();
    }).catch(() => setError("The camera could not be opened. Allow camera access, or use a scanner or type the code."));
    return () => { done = true; clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()); };
  }, []);
  return (
    <div className="camera">
      {error ? <p className="error">{error}</p> : <video ref={video} muted playsInline aria-label="Camera view for scanning labels" />}
    </div>
  );
}
