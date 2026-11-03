import { test } from "node:test";
import assert from "node:assert/strict";
import {
    generateKeyPairSync,
    sign,
    randomBytes,
    createHash,
} from "node:crypto";
import { verifySignature, targets, updateIndexes } from "./update-manifest.mjs";
const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const id = randomBytes(8),
    data = Buffer.from("installer fixture");
const pub = Buffer.concat([
    Buffer.from("Ed"),
    id,
    publicKey.export({ format: "der", type: "spki" }).subarray(-32),
]);
const key = Buffer.from(
    `untrusted comment: fixture\n${pub.toString("base64")}\n`,
).toString("base64");
const signature = sign(
    null,
    createHash("blake2b512").update(data).digest(),
    privateKey,
);
const packet = Buffer.concat([Buffer.from("ED"), id, signature]);
const comment = "timestamp:123";
const globalSig = sign(
    null,
    Buffer.concat([signature, Buffer.from(comment)]),
    privateKey,
);
const encoded = Buffer.from(
    `untrusted comment: fixture\n${packet.toString("base64")}\ntrusted comment: ${comment}\n${globalSig.toString("base64")}\n`,
).toString("base64");
test("publisher verifies signed bytes and rejects modified files, comments or key ids", () => {
    verifySignature(data, encoded, key);
    assert.throws(
        () => verifySignature(Buffer.from("changed installer"), encoded, key),
        /mismatch/,
    );
    assert.throws(
        () =>
            verifySignature(
                data,
                Buffer.from(
                    Buffer.from(encoded, "base64")
                        .toString()
                        .replace("timestamp:123", "timestamp:124"),
                ).toString("base64"),
                key,
            ),
        /comment signature/,
    );
    assert.throws(() => verifySignature(data, encoded, "bad-key"), /format/);
});
test("four release targets are explicit and Linux updater uses AppImage", () => {
    assert.equal(Object.keys(targets).length, 4);
    assert.deepEqual(targets["linux-x86_64"], [
        "x86_64-unknown-linux-gnu",
        ".AppImage",
    ]);
});
test("legacy and migrated clients receive identical signed packages through their trusted hosts", () => {
    const release = {
        version: "0.1.12",
        notes: "迁移",
        pub_date: "2026-11-03T00:00:00Z",
        platforms: Object.fromEntries(
            Object.keys(targets).map((platform) => [
                platform,
                { signature: encoded },
            ]),
        ),
    };
    const indexes = updateIndexes(release);
    assert.deepEqual(Object.keys(indexes), [
        "capybara-latest.json",
        "capybara-current.json",
        "capybara-hub.json",
    ]);
    for (const platform of Object.keys(targets)) {
        const legacy = indexes["capybara-latest.json"].platforms[platform];
        const current = indexes["capybara-current.json"].platforms[platform];
        assert.equal(new URL(legacy.url).origin, "https://taige.us");
        assert.equal(new URL(current.url).origin, "https://capybarago.uk");
        assert.equal(
            new URL(legacy.url).pathname,
            new URL(current.url).pathname,
        );
        assert.equal(current.signature, legacy.signature);
        verifySignature(data, current.signature, key);
    }
});
