# Cómo lograr que la app mueva plata real en BTG Chile

## Bloqueo actual

BTG Pactual Chile (retail digital) **no publica una API abierta** para que una app externa envíe órdenes sola.

Por eso hoy la app puede:

- analizar y predecir
- operar en **paper**
- preparar drafts de orden

pero **no puede debitar/ejecutar** tu cuenta BTG sin un canal oficial.

## Camino oficial (el único seguro)

### 1) Tener cuenta fondeada en BTG
App/web BTG Inversiones Digitales → abono por Fintoc/transferencia/botón de pago.

### 2) Pedir a BTG habilitación de ejecución automatizada
Opciones típicas en mercado chileno:

- **DMA / FIX** vía corredora (BTG como intermediario ante Bolsa de Santiago)
- **API/partner** de ruteo de órdenes (si BTG lo habilita para tu perfil)
- Cuenta/mesa con capacidades de algo trading

Contactos útiles:

- `contactodigital@btgpactual.com`
- `contactochile@btgpactual.com`
- `800 386 800`

### 3) Plantilla de correo (cópiala)

Asunto: Solicitud de acceso API/DMA para ejecución automatizada de órdenes

Hola equipo BTG,

Soy cliente de BTG Pactual Chile y estoy construyendo un sistema propio de inversión automatizada (Python).

Necesito un canal oficial para:
1) consultar saldo/custodia,
2) enviar órdenes de compra/venta de renta variable,
3) consultar estado de órdenes y fills,
4) ambiente sandbox + producción.

¿Pueden indicarme si para mi perfil (retail/private/institutional) existe:
- API REST de trading,
- DMA FIX 4.4 a través de BTG,
- u otra plataforma homologada para algo trading?

Quedo atento para completar onboarding técnico, contratos y pruebas.

Saludos,
[Nombre]
[RUT]
[N° cuenta BTG]
[Teléfono]

### 4) Cuando BTG entregue acceso
Configurar en `.env`:

```bash
ADVISOR_BTG_LIVE_ENABLED=true
ADVISOR_BTG_ACCOUNT_ID=...
ADVISOR_BTG_LIVE_TOKEN=...
```

Luego implementamos el cliente oficial en `src/advisor/execution/live_btg.py` y activamos autopilot live con límites estrictos.

## Lo que NO haremos

- Scraping / reverse engineering del Home Broker
- Usar tokens de sesión no oficiales
- Automatizar con bots frágiles que violen términos de BTG

Eso puede cerrar tu cuenta y es inseguro.

## Mientras tanto (operación real asistida)

1. Autopilot paper valida la estrategia
2. La app genera la orden exacta
3. Tú la ejecutas en BTG en 20–30 segundos
4. Cuando exista API, el mismo plan se envía solo
