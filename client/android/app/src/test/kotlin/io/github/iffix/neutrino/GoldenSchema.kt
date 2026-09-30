package io.github.iffix.neutrino

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * The hub's golden, `hub/tests/web/channel_schema.json`, read by its path, and a check of a JSON
 * value against one of its models for the parts of JSON Schema pydantic writes.
 */
object GoldenSchema {
    private val golden: JsonObject by lazy {
        Json.parseToJsonElement(RepositoryFiles.text("hub/tests/web/channel_schema.json")).jsonObject
    }

    /** The protocol number the golden pins. */
    val protocol: Int
        get() = golden["protocol"]!!.jsonPrimitive.intOrNull!!

    /**
     * One model's schema.
     *
     * @param name The model, such as `ChannelHello`.
     * @return Its schema.
     */
    fun model(name: String): JsonObject = golden["models"]!!.jsonObject[name]!!.jsonObject

    /**
     * The property names of one model, or of one of its definitions.
     *
     * @param name The model or definition.
     * @return The names.
     */
    fun properties(name: String): Set<String> = (definition(name)["properties"] as JsonObject).keys

    /**
     * Every way a value breaks a model.
     *
     * @param value The value.
     * @param name The model.
     * @param isStrict Whether a field the model does not name is a break, the rule for what this app writes.
     * @return One line per break; empty when the value conforms.
     */
    fun problems(value: JsonElement, name: String, isStrict: Boolean = true): List<String> {
        val schema = model(name)
        return check(value, schema, schema, name, isStrict)
    }

    private fun definition(name: String): JsonObject {
        val models = golden["models"]!!.jsonObject
        models[name]?.let { return it.jsonObject }
        for (model in models.values) {
            val defs = model.jsonObject["\$defs"] as? JsonObject ?: continue
            defs[name]?.let { return it.jsonObject }
        }
        throw IllegalArgumentException("the golden has no $name")
    }

    private fun check(
        value: JsonElement,
        schema: JsonObject,
        root: JsonObject,
        path: String,
        isStrict: Boolean,
    ): List<String> {
        schema["\$ref"]?.let { ref ->
            val name = ref.jsonPrimitive.content.substringAfterLast('/')
            val defs = root["\$defs"] as? JsonObject
            val target = defs?.get(name)?.jsonObject ?: definition(name)
            return check(value, target, root, path, isStrict)
        }
        (schema["anyOf"] as? JsonArray)?.let { options ->
            val fits = options.any { check(value, it.jsonObject, root, path, isStrict).isEmpty() }
            return if (fits) emptyList() else listOf("$path matches none of anyOf")
        }
        val type = (schema["type"] as? JsonPrimitive)?.content ?: return emptyList()
        return when (type) {
            "object" -> checkObject(value, schema, root, path, isStrict)

            "array" -> {
                val items = value as? JsonArray ?: return listOf("$path is not an array")
                val itemSchema = schema["items"] as? JsonObject ?: return emptyList()
                items.flatMapIndexed { index, item -> check(item, itemSchema, root, "$path[$index]", isStrict) }
            }

            "string" -> if (value is JsonPrimitive && value.isString) emptyList() else listOf("$path is not a string")

            "integer" -> if (value is JsonPrimitive && !value.isString && value.longOrNull != null) {
                emptyList()
            } else {
                listOf("$path is not an integer")
            }

            "boolean" -> if (value is JsonPrimitive && !value.isString && value.booleanOrNull != null) {
                emptyList()
            } else {
                listOf("$path is not a boolean")
            }

            "null" -> if (value is JsonNull) emptyList() else listOf("$path is not null")

            else -> listOf("$path has a type the check does not know: $type")
        }
    }

    private fun checkObject(
        value: JsonElement,
        schema: JsonObject,
        root: JsonObject,
        path: String,
        isStrict: Boolean,
    ): List<String> {
        val instance = value as? JsonObject ?: return listOf("$path is not an object")
        val properties = schema["properties"] as? JsonObject ?: JsonObject(emptyMap())
        val required = (schema["required"] as? JsonArray)?.map { it.jsonPrimitive.content }.orEmpty()
        val problems = mutableListOf<String>()
        for (name in required) if (name !in instance) problems += "$path lacks required $name"
        val additional = schema["additionalProperties"]
        for ((name, field) in instance) {
            val fieldSchema = properties[name] as? JsonObject
            when {
                fieldSchema != null -> problems += check(field, fieldSchema, root, "$path.$name", isStrict)
                additional is JsonObject -> problems += check(field, additional, root, "$path.$name", isStrict)
                additional is JsonPrimitive && additional.booleanOrNull == true -> Unit
                isStrict -> problems += "$path.$name is not in the model"
            }
        }
        return problems
    }
}
