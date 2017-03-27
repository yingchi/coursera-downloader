import os
from Crypto.Cipher import AES

key1 = 'ἀλήθεια,καὶἡζωή'    # 32 bits in utf-8
key2 = 'Ἰησοῦς88'           # 16 bits in utf-8
key1 = key1.encode('utf-8')
key2 = key2.encode('utf-8')


def clearScreen():
    if os.name == 'posix':
        os.system('clear')  # clear the terminal window
    else:
        os.system('cls')
    # The function os.name() returns the OS-dependent module (e.g., posix, doc, mac,...)
    # posix: module provides access to operating system functionality that is standardized 
    # by the C Standard and the POSIX standard (a thinly disguised Unix interface).


def createPass():
    print('One time setup user and password\n')

    email = str(input('Enter your e-mail address: '))
    print(email, '\n')

    password = str(input('Enter your Coursera password: '))
    print('*' * len(password), '\n')

    strInput = email + ':' + password
    encryptedText = encrypt(strInput, key1, key2)

    fileCreate('coursera.pass', encryptedText)

    return email, password


def decrypt(strInput, key1, key2):
    """ decrypt an encrypted string with key1 and key2
    """
    obj2 = AES.new(key1, AES.MODE_CBC, key2)
    decryptedText = obj2.decrypt(strInput)

    return decryptedText


def encrypt(strInput, key1, key2):
    """ encrypt a string input with key1 and key2
    """
    key1 = key1.decode('utf-8')
    key1 = key1.encode('utf-8')

    obj = AES.new(key1, AES.MODE_CBC, key2)
    strInput = pad(strInput)

    encryptedText = obj.encrypt(strInput)
    return encryptedText


def fileCreate(strNamaFile, strData):
    """
    Create a text file
    """

    f = open(strNamaFile, 'wb')
    f.write(strData)
    f.close()


def getUserPass(strPasswordFile):
    f = open(strPasswordFile, 'rb')
    strText = f.read()
    f.close()

    decryptedText = decrypt(strText, key1, key2).decode()
    decryptedText = decryptedText.strip()
    email = decryptedText.split(":")[0]
    password = decryptedText.split(":")[1]

    return email, password


def pad(s):
    """ pad the strings to b`e multiples of 16 for AES use
    """
    if len(s) % 16 == 0:
        return s
    else:
        return s + ((16 - len(s) % 16) * ' ')


def readTextFile(strNamaFile):
    """ read from a text file
    """

    fText = open(strNamaFile, 'rb')
    strText = ''

    for baris in fText.readlines():
        strText += baris
    fText.close()

    return strText
