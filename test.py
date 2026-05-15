# IMPLEMENTACIONES
# Cómo se envía

class EmailSender:
    def enviar(self, mensaje):
        print(f"Enviando EMAIL: {mensaje}")


class WhatsAppSender:
    def enviar(self, mensaje):
        print(f"Enviando WHATSAPP: {mensaje}")


# ABSTRACCIÓN
# Qué tipo de notificación es

class Notificacion:

    def __init__(self, sender):
        self.sender = sender

    def enviar(self, mensaje):
        self.sender.enviar(mensaje)


# ABSTRACCIÓN EXTENDIDA

class NotificacionUrgente(Notificacion):

    def enviar(self, mensaje):
        mensaje = "URGENTE -> " + mensaje
        self.sender.enviar(mensaje)


# USO

email = EmailSender()
whatsapp = WhatsAppSender()

n1 = Notificacion(email)
n1.enviar("Hola Tomas")

print()

n2 = NotificacionUrgente(whatsapp)
n2.enviar("Servidor caido")