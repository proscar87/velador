# Contribuir a Velador

- Issues y PRs bienvenidos, en español o inglés.
- Reglas del código: sin llamadas de red propias (iot_class `calculated`), sin notificaciones push (la señal vive en Repairs, entidades y eventos), sin dependencias externas en `requirements`.
- Todo cambio debe pasar `hassfest` y la validación HACS del CI.
- Un PR = un cambio. Describe el escenario real que lo motiva (esta integración nació de fallas reales, no de features imaginarias).
- Secretos y datos reales JAMÁS entran al repo (Garita corre en CI y bloquea).

## Versionado

- **Una ola de features = un minor** (`0.9.0`). Arreglos, metadata y empaquetado = un patch (`0.9.1`).
- **Un release por versión, y un commit por release.** Dos tags sobre el mismo commit dejan un release entregando un manifest que dice otra cosa (pasó con `v0.6.0`, que entrega `0.7.0`). Si dos olas caen juntas, se publican como una sola versión.
- Antes de taggear, estos cuatro tienen que decir lo mismo: `manifest.json` → entrada del `CHANGELOG.md` → tag de git → release de GitHub.
- El piso de `hacs.json` es un contrato, no decoración: si el código usa una API de core, ahí va la versión que la introdujo. Hoy `2024.8` por `state.last_reported`.
- **La v1.0 se reserva.** Un 1.0 dice "estable y probado por gente que no soy yo": se marcará cuando esté en la tienda default de HACS y haya uso real de terceros — no por haber terminado el roadmap.
