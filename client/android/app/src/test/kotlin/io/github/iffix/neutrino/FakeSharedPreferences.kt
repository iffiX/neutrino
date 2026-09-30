package io.github.iffix.neutrino

import android.content.SharedPreferences

/** SharedPreferences held in a map, for tests on the JVM. */
class FakeSharedPreferences : SharedPreferences {
    /** What has been committed. */
    val values: MutableMap<String, Any?> = mutableMapOf()

    override fun getAll(): MutableMap<String, *> = values.toMutableMap()

    override fun getString(key: String, defValue: String?): String? = values[key] as? String ?: defValue

    @Suppress("UNCHECKED_CAST")
    override fun getStringSet(key: String, defValues: MutableSet<String>?): MutableSet<String>? =
        values[key] as? MutableSet<String> ?: defValues

    override fun getInt(key: String, defValue: Int): Int = values[key] as? Int ?: defValue

    override fun getLong(key: String, defValue: Long): Long = values[key] as? Long ?: defValue

    override fun getFloat(key: String, defValue: Float): Float = values[key] as? Float ?: defValue

    override fun getBoolean(key: String, defValue: Boolean): Boolean = values[key] as? Boolean ?: defValue

    override fun contains(key: String): Boolean = key in values

    override fun edit(): SharedPreferences.Editor = Editor()

    override fun registerOnSharedPreferenceChangeListener(
        listener: SharedPreferences.OnSharedPreferenceChangeListener,
    ) = Unit

    override fun unregisterOnSharedPreferenceChangeListener(
        listener: SharedPreferences.OnSharedPreferenceChangeListener,
    ) = Unit

    private inner class Editor : SharedPreferences.Editor {
        private val staged = mutableMapOf<String, Any?>()
        private val removed = mutableSetOf<String>()
        private var isCleared = false

        override fun putString(key: String, value: String?) = apply { staged[key] = value }

        override fun putStringSet(key: String, values: MutableSet<String>?) = apply { staged[key] = values }

        override fun putInt(key: String, value: Int) = apply { staged[key] = value }

        override fun putLong(key: String, value: Long) = apply { staged[key] = value }

        override fun putFloat(key: String, value: Float) = apply { staged[key] = value }

        override fun putBoolean(key: String, value: Boolean) = apply { staged[key] = value }

        override fun remove(key: String) = apply { removed += key }

        override fun clear() = apply { isCleared = true }

        override fun commit(): Boolean {
            if (isCleared) values.clear()
            removed.forEach { values.remove(it) }
            values.putAll(staged)
            return true
        }

        override fun apply() {
            commit()
        }
    }
}
