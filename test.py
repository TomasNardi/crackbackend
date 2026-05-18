# Clase encargada de enviar emails
# Esta seria la "dependencia"
class EmailService:

    # Metodo para enviar un mensaje
    def enviar(self, mensaje):

        # Simulamos el envio del email
        print(f"Enviando email: {mensaje}")


# Clase principal de negocio
class UsuarioService:

    # El constructor recibe una dependencia
    # En este caso: email_service
    # NO la crea adentro, la recibe desde afuera
    def __init__(self, email_service):

        # Guardamos la dependencia en la instancia
        self.email_service = email_service

    # Metodo para registrar usuarios
    def registrar_usuario(self, nombre):

        # Simulamos el registro
        print(f"Usuario {nombre} registrado")

        # Usamos la dependencia inyectada
        # para enviar el email
        self.email_service.enviar("Bienvenido!")


# =========================
# INYECCION DE DEPENDENCIA
# =========================

# Creamos la dependencia
email_service = EmailService()

# Creamos UsuarioService
# y le INYECTAMOS la dependencia
usuario_service = UsuarioService(email_service)

# Ejecutamos el metodo
usuario_service.registrar_usuario("Tomas")