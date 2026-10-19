# Body-surface masks

Created 2026-10-17 with the built-in image-generation tool from the seven supplied sibling photographs. Each PNG is a luminance mask: white painted panels, black protected surfaces and background. Original photographs were not edited. The matching source is the same filename one folder above. SGL and RAPCAP share Ranger's supplied reference and mask.

Assets: `ranger.png`, `raptor.png`, `super-duty.png`, `everest.png`, `transit.png`, `amarok.png`, `territory.png`.

Prompt set used per source:

> Produce a precise black-and-white segmentation mask at the same framing and aspect ratio as the original. White only on painted sheet metal and body-colour plastic: hood, painted roof, metal pillars, fenders, doors, painted handles and cargo side panels. Black on background, ground and shadows, lamps and reflectors, glass, grille, badges, chrome, roof rails, mirrors, black trim, tyres, wheels, running boards, black bumpers and stickers. Trace the photo's surface boundaries. No new viewpoint, text, grey shading or geometry. The mask will be laid over the unchanged source photo, so registration must be preserved.

One correction pass removed the Raptor's central silver skid plate, Territory's lower silver strip, and Transit's headlamp/DRL outlines and chrome lip. The correction prompts referenced the generated mask as edit target and the original photo as reference, requesting those areas turn black while preserving the rest of the mask.

Consumed by `ProfilePhoto.tsx` as SVG luminance masks, fitted to the source photo's dimensions. Saved plant HEX comes from the existing colour appearance API. The images illustrate appearance; they do not calibrate paint or change measurements.
