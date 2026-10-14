package com.animan.app

import android.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

object CryptoBridge {
    @JvmStatic fun decrypt(data: String, key: String, iv: String, unpad: Boolean): String {
        val cipher = Cipher.getInstance(if (unpad) "AES/CBC/PKCS5Padding" else "AES/CBC/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(Base64.decode(key, Base64.DEFAULT), "AES"),
            IvParameterSpec(Base64.decode(iv, Base64.DEFAULT)))
        return Base64.encodeToString(cipher.doFinal(Base64.decode(data, Base64.DEFAULT)), Base64.NO_WRAP)
    }
}
