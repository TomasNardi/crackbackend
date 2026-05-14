import time
class Mobile:
    SIZES = ["s", "m", "l"]

    def __init__(self, brand, size):
        self._material = 'Metal and Plastic'

        self.brand = brand
        self.size = size

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, value):
        if value in Mobile.SIZES:
            self._size = value
        else:
            raise Exception("Invalid size")

    @property
    def brand(self):
        return self.__brand

    @brand.setter
    def brand(self, value):
        if len(value.strip()) < 2:
            raise Exception("Invalid brand")

        self.__brand = value


class Order(Mobile):

    PAYMENT_METHODS = ["Credit Card", "Debit Card", "Cash"]

    def __init__(self, brand, size, method):
        super().__init__(brand, size)

        self.method = method
        self.Validation

    @property
    def method(self):
        return self.__method

    @method.setter
    def method(self, value):
        if value in Order.PAYMENT_METHODS:
            self.__method = value
        else:
            raise Exception('Invalid payment info')
    
    def Validation(self):
        time.sleep(3)
        print('Payment validation')


usu1 = Order('Samsung', "m", "Credit Card")

print(
    f'Size: {usu1.size}, '
    f'Brand: {usu1.brand}, '
    f'Material: {usu1._material}, '
    f'Payment: {usu1.method}'
)