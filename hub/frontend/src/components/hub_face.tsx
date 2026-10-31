import wolfAngry from "@hub_icons/wolf_angry.svg";
import wolfHappy from "@hub_icons/wolf_happy.svg";
import wolfOpen from "@hub_icons/wolf_open.svg";
import wolfSad from "@hub_icons/wolf_sad.svg";
import wolfWaiting from "@hub_icons/wolf_waiting.svg";

import "./hub_face.css";

/** The faces the panel shows, files of `images/icons/neutrino_hub/`. */
const FACES = {
  angry: wolfAngry,
  happy: wolfHappy,
  open: wolfOpen,
  sad: wolfSad,
  waiting: wolfWaiting,
};

interface HubFaceProps {
  face: keyof typeof FACES;
}

/** One face of the hub's wolf. It fills the box that holds it. */
export function HubFace({ face }: HubFaceProps) {
  return <img className="hub_face" src={FACES[face]} alt="" />;
}
