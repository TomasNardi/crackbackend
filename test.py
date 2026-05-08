class User: 
    
    user_id = 0 
    
    def __init__(self, name, apellido='troll'):
        self.name = name
        self.apellido = apellido
        
        User.user_id += 1 
        self.id = User.user_id
        
        self.__gender = 'En desarrollo'
        
    @classmethod
    def instancia(cls, name):
        return cls(name)
    
    # getter
    @property 
    def gender(self): 
        return self.__gender
    
    # setter
    @gender.setter
    def gender(self, value): 
        if value == 'masculino': 
            value = 'femeninio'
        self.__gender = value
        

usu1 = User('tomas', 'nardi')

print(usu1.gender)

usu1.gender = 'masculino'

print(usu1.gender)
print('-----'*10)
usu2 = User.instancia('test')

print(usu2.name , usu2.apellido , usu2.user_id , usu2.gender)
usu2.gender = 'masculino'
print(usu2.name , usu2.apellido , usu2.user_id , usu2.gender)
