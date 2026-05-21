from abc import ABC, abstractmethod

# clase abstracta
class Validation(ABC):
    @abstractmethod
    def validation_user(self): 
        print('Me obligaron a verificar la validez del user')
        
# Interfaz
class SSO(ABC):
    @abstractmethod
    def connection(self):
        pass 
    
    @abstractmethod
    def control(self):
        pass 

# Dos posibles Logs
class Login_Manual: 
    def login(self): 
        print('Me logeo Manualmente')

class Login_Automatic:
    def login(self):  
        print('Me logeo Automaticamente')

# -----------------------------------------------

class Login(Validation, SSO):
    # atributo de clase
    USER_ID = 0 
    def __init__(self ,user_name, login_method):
        self.login_method = login_method
        self.user_name = user_name
        self.USER_ID = + 1 
        self.user_id = self.USER_ID
        
    @property
    def user_name(self):
        """The user_name property."""
        return self._user_name
    @user_name.setter
    def user_name(self, value):

        if (len(value) >= 5): 
            print('Uso el setter para convertir username')
        else: 
            raise Exception('El username debe tener al menos 5 caracteres')
    
        self._user_name = value
    
    # Inyecto dependencias / dependo de la la instancia.
    def new_login(self): 
        # Implemento el metodo de la clase abstracta
        self.validation_user()
        # Implemento el metodo inyectado
        self.login_method.login()
    
    def connection(self):
        print('Conectado, firme el contracto y estoy obligado a realizar la conexion')
        
    def control(self):
        return super().control()

user1 = Login('Tester',Login_Automatic())
print(f'Nueva conexion {user1.user_name}, detectada N# {user1.user_id}')
user1.new_login()
user1.connection()




        
        
    
    