# Los metodos abstractos obligaran a la clase instanciada a implementar el metodo en la instancia 
from abc import abstractmethod
# ABC Meta se usa para declarar la clase como una interfaz
from abc import ABCMeta

# Creo la interface con abc (abstract base class)
# El decorador abstractmethod, obliga a los herederos a implementar el metodo 
class Mando(metaclass=ABCMeta):
    @abstractmethod
    def siguiente_canal(self):
        pass

    @abstractmethod
    def canal_anterior(self):
        pass

    @abstractmethod
    def subir_volumen(self):
        pass

    @abstractmethod
    def bajar_volumen(self):
        pass

# Creo la  clase y firmo el contrato con Mando
# Mando no es una clase comun, es una interfaz
class MandoSamsung(Mando):
    def siguiente_canal(self):
        print("Samsung->Siguiente")
    def canal_anterior(self):
        print("Samsung->Anterior")
    def subir_volumen(self):
        print("Samsung->Subir")
    def bajar_volumen(self):
        print("Samsung->Bajar")


m1 = MandoSamsung()

m1.subir_volumen()