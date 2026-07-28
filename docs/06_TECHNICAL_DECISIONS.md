# 06 — Decisiones técnicas

## DEC-001
**Decisión:** usar un monorepositorio modular.

**Motivo:** los módulos comparten usuarios, fincas, lotes, contratos y datos,
pero deben poder evolucionar y probarse por separado.

## DEC-002
**Decisión:** no subir ortofotos, GeoPackage, pesos de modelos, datasets,
resultados generados ni credenciales a Git.

**Motivo:** seguridad, tamaño y rendimiento del repositorio.

## DEC-003
**Decisión:** conservar los sistemas importados sin refactorización destructiva
durante el primer commit.

**Motivo:** mantener una línea base reproducible antes de integrar.
