# Contribuir a Velador

- Issues y PRs bienvenidos, en español o inglés.
- Reglas del código: sin llamadas de red propias (iot_class `calculated`), sin notificaciones push (la señal vive en Repairs, entidades y eventos), sin dependencias externas en `requirements`.
- Todo cambio debe pasar `hassfest` y la validación HACS del CI.
- Un PR = un cambio. Describe el escenario real que lo motiva (esta integración nació de fallas reales, no de features imaginarias).
- Secretos y datos reales JAMÁS entran al repo (Garita corre en CI y bloquea).
