# Contribuir a Velador

- Issues y PRs bienvenidos, en español o inglés.
- Reglas del código: sin llamadas de red propias (iot_class `calculated`), sin notificaciones push (la señal vive en Repairs, entidades y eventos), sin dependencias externas en `requirements`.
- Todo cambio debe pasar `hassfest` y la validación HACS del CI.
- Un PR = un cambio. Describe el escenario real que lo motiva (esta integración nació de fallas reales, no de features imaginarias).
- Secretos y datos reales JAMÁS entran al repo (Garita corre en CI y bloquea).

## Versionado

- **Una ola de features = un minor** (`0.9.0`). Arreglos, metadata y empaquetado = un patch (`0.9.1`).
- **Un release por versión, y un commit por release.** Dos tags sobre el mismo commit dejan un release entregando un manifest que dice otra cosa (pasó con `v0.6.0`, que entrega `0.7.0`). Si dos olas caen juntas, se publican como una sola versión.
- Antes de taggear, estos cuatro tienen que decir lo mismo: `manifest.json` → entrada del `CHANGELOG.md` → tag de git → release de GitHub. Lo verifica `scripts/check_version.py`, que corre en CI — pero córrelo tú antes de taggear, porque en CI ya es tarde.
- **Cambios que no tocan `custom_components/` no llevan bump ni release** (CI, docs, blueprints, dashboard). Subir la versión por algo que el usuario no recibe le cuesta una actualización en HACS a cambio de nada.
- El piso de `hacs.json` es un contrato, no decoración: si el código usa una API de core, ahí va la versión que la introdujo. Hoy `2024.8` por `state.last_reported`.
- **La v1.0 se reserva.** Un 1.0 dice "estable y probado por gente que no soy yo": se marcará cuando esté en la tienda default de HACS y haya uso real de terceros — no por haber terminado el roadmap.

## Probar

- **Los dobles no saben lo que no existe.** Si el código lee un atributo de un objeto de HA, verifícalo contra HA de verdad antes de liberar. Un `getattr(obj, "x", None)` con fallback silencioso se ve idéntico funcionando y roto: la detección de breaking change de v0.7 estuvo muerta tres versiones porque leía `hass.config.version`, que no existe, y siempre caía al `"?"`. Las pruebas con stubs pasaban — el stub no sabe que el atributo no existe.
- Prefiere el atributo importado (`from homeassistant.const import __version__`) sobre el `getattr` defensivo: si desaparece, quieres un `ImportError` ruidoso en CI, no un fallback callado en producción.
- Un fallback silencioso necesita justificación explícita en el código. `last_reported` la tiene (`or state.last_updated`, para instalaciones viejas); si no puedes escribir esa justificación en una línea, no pongas el fallback.
