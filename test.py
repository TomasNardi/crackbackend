# =========================
# MOTORES
# =========================

class MotorNafta:

    def arrancar(self):
        print('Motor a nafta encendido')


class MotorElectrico:

    def arrancar(self):
        print('Motor electrico encendido')


# =========================
# AUTO
# =========================

class Auto:

    # Inyeccion de dependencias:
    # el auto RECIBE el motor desde afuera
    def __init__(self, motor):

        # guardo el objeto motor dentro del auto
        self.motor = motor

    def arrancar_auto(self):

        print('El auto intenta arrancar...')

        # uso el motor que me pasaron
        self.motor.arrancar()


# =========================
# CREO LOS MOTORES
# =========================

motor_nafta = MotorNafta()
motor_electrico = MotorElectrico()


# =========================
# CREO AUTOS
# =========================

auto1 = Auto(motor_nafta)
auto2 = Auto(motor_electrico)


# =========================
# PRUEBO
# =========================

auto1.arrancar_auto()

print('---')

auto2.arrancar_auto()