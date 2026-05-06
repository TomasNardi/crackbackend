class User(): 
    user_id_current = 0 

    def __init__(self,nombre):
        self.nombre = nombre 
        User.user_id_current += 1
        self.user_id = User.user_id_current

    @classmethod
    def admin(cls,nombre):
        print(f'Creando instancia de {nombre}')
        return cls(nombre)
    
    def saludar(self):
        print(f'hola desde metodo {self.nombre}')


user1 = User('tomas')
user2 = User('pepe')
user3 = User('caca')
user4 = User.admin('admin')

user1.saludar()

print(user1.nombre)
print(user2.nombre)
print(user3.nombre)
print(user4.nombre)


print(user1.user_id)
print(user2.user_id)
print(user3.user_id)
print(user4.user_id)



