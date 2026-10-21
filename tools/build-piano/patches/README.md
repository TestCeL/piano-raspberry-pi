# Parches locales sobre FigBug/Piano v1.0.14

Se aplican automáticamente en `build-in-container.sh` después de clonar, en orden alfabético.

| Parche | Motivo | Efecto funcional |
|--------|--------|------------------|
| `0001-fft-order-constructor-cxx20.patch` | `plugin/Source/fft.h:815` declara el constructor como `fft_order<N>()`. En C++20 un *template-id* no puede nombrar un constructor (CWG DR 2237). GCC 12, el compilador de Debian 12, lo rechaza con un error; GCC ≥ 14 y Clang solo avisan, y por eso compila en el CI de upstream (Ubuntu reciente). Se cambia a `fft_order()`. | Ninguno: es la misma función con la sintaxis estándar. |
