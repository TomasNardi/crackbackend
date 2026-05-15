class User():
    USER_ID = 0 
    def __init__(self, name , lastname, dni , email):
        self.name = name
        self.lasname =  lastname
        self.dni = dni
        self.email = email
        User.USER_ID =+ 1 
        self.user_id = User.USER_ID
        
    @property
    def name(self):
        return self._name
    
    @name.setter
    def name(self, value):
        self._name = value

usu1 = User('tomi','nardi','39558339','tomas.nardi@hotmail.com')

print(f"{usu1.name} , {usu1.user_id}")