# 📄 Descarga de Órdenes en PDF - CRACK TCG

## Descripción

Hemos agregado un sistema de generación y descarga de PDFs de órdenes directamente desde el panel de administración de Django. El dueño de la tienda puede descargar un resumen profesional de cada orden con un solo clic.

## ¿Dónde está el botón?

### En la lista de órdenes (ListView)
- Accede a **Órdenes** en el admin
- Verás una nueva columna **PDF** con un botón dorado **📄 PDF**
- Haz clic para descargar la orden

### En el detalle de la orden (Detail View)
- Dentro de cada orden, hay un botón **📄 PDF** en la fila de acciones
- También puedes usar la acción de lote "⬇ Descargar seleccionadas como ZIP"

## ¿Qué incluye el PDF?

Cada PDF contiene:

1. **Header Profesional**
   - Logo/Marca: "CRACK TCG"
   - Título: "COMPROBANTE DE ORDEN"

2. **Datos de la Orden**
   - Código de orden (ej: A9K3X2)
   - Fecha y hora de creación
   - Estado actual (Pagada/Pendiente/Cancelada)

3. **Datos del Cliente**
   - Nombre completo
   - Email
   - Teléfono
   - Método de pago utilizado
   - (Todo en fondo beige con borde dorado)

4. **Tabla de Productos**
   - Nombre del producto
   - Precio unitario
   - Cantidad
   - Subtotal por línea
   - (Header dorado con texto blanco)

5. **Resumen de Totales**
   - Subtotal
   - Descuento por código (si aplica)
   - Descuento por efectivo (si aplica)
   - Costo de envío (si aplica)
   - **TOTAL** destacado en dorado

6. **Información de Envío**
   - Tipo de envío (Domicilio/Retiro)
   - Dirección completa
   - Provincia y código postal
   - Tracking de Paq.ar (si ya fue despachado)

7. **Pie de Página**
   - Mensaje de agradecimiento

## Diseño Visual

El PDF utiliza la paleta de colores de CRACK TCG:
- **Principal**: Dorado (#C8972E)
- **Secundario**: Marrón oscuro (#8B6914)
- **Fondo**: Beige claro (#F5F1E8)
- **Bordes**: Dorado claro (#D4A574)

## Formato del Archivo

Los PDFs se descargan con el nombre: `orden_CODIGO.pdf`

Ejemplo: `orden_A9K3X2.pdf`

## Acciones Disponibles

### Acción Individual
1. Ve a la lista de órdenes
2. Haz clic en el botón **📄 PDF** en cualquier fila
3. Se descargará automáticamente el PDF

### Acción en Lote
1. Selecciona una o más órdenes (checkbox)
2. En el menú de acciones, elige "⬇ Descargar seleccionadas como ZIP"
3. Si seleccionas una orden → Se descarga el PDF directamente
4. Si seleccionas múltiples → Verás un mensaje para descargarlas de una en una

## Requisitos Técnicos Instalados

```
reportlab==4.0.9  # Generación de PDFs con diseño personalizado
pillow>=9.0.0     # Soporte para imágenes en PDFs
chardet            # Detección de charset
```

## Flujo de Uso Típico

1. **El cliente compra** → Se crea una orden (estado: Pendiente)
2. **El cliente paga** → Se aprueba el pago (estado: Pagada)
3. **El dueño accede al admin** → Administrador/Órdenes
4. **Busca/filtra la orden** → Puede usar código, nombre, email
5. **Haz clic en 📄 PDF** → Se descarga el comprobante
6. **El dueño puede imprimir, enviar por email, etc.**

## Casos de Uso

✅ **Enviar al cliente** - Forwarding por correo como recibo
✅ **Imprimir** - Para archivo físico o etiquetado
✅ **Referencia rápida** - En caso de consultas del cliente
✅ **Respaldo** - Guardar como constancia de venta

## Solución de Problemas

**P: El botón PDF no aparece**
- R: Asegúrate de estar usando la última versión del código
- Reinicia el servidor Django: `py manage.py runserver`

**P: El PDF se ve mal o tiene errores**
- R: Verifica que todos los datos de la orden estén completos
- Revisa los logs del Django en consola

**P: No puedo descargar múltiples órdenes como ZIP**
- R: Esta funcionalidad está disponible para descarga individual
- Puedes descargar cada orden por separado

## Futuras Mejoras (TODO)

- [ ] Descarga en ZIP de múltiples órdenes
- [ ] Envío automático de PDF por email al cliente
- [ ] Exportación a otros formatos (Excel, CSV)
- [ ] Escaneo de QR en el PDF para seguimiento
- [ ] Logo customizable por cliente

---

**¿Necesitas ayuda?** Contacta al equipo de desarrollo si tienes preguntas sobre la funcionalidad.
