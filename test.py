class Celular:

    def __init__(self, marca, modelo):

        self.marca = marca
        # atributo PUBLICO
        # cualquiera puede leer/modificar

        self._conexion = 'mysql'
        # atributo PROTEGIDO
        # uso interno de la clase (convención)

        self.__imei = '123456'
        # atributo PRIVADO
        # más encapsulado


class Celular_comprar(Celular):

    def __init__(self, marca, modelo, metodo_pago):

        super().__init__(marca, modelo)

        self.metodo = metodo_pago
        # property publica
        # llama al setter

    @property
    def metodo(self):

        return self.__metodo
        # devuelve atributo privado real

    @metodo.setter
    def metodo(self, value):

        if value not in ['tarjeta', 'efectivo']:
            raise ValueError('Metodo invalido')

        self.__metodo = value
        # atributo privado interno


cel_1 = Celular_comprar('samsung', 's22', 'tarjeta')

cel_1.metodo = 'efectivo'

print(cel_1.metodo)
print(cel_1.marca)
print(cel_1._conexion)



def funcion(x):
    def funcion_modificada():
        print('decorador')
        x()
    return funcion_modificada

@funcion
def saludarte():
    print('Hola')

saludarte()
