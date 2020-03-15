from __future__ import absolute_import, division, print_function, unicode_literals

#import tensorflow.compat.v1 as tf
import tensorflow as tf
import tensorflow_datasets as tfds


#helper libraries
import numpy as np
import matplotlib.pyplot as plt
import time

#get rid of some interpreter warnings
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

tf.get_logger().setLevel('ERROR')

'''
SETUP THE INPUT PIPELINE (portugal to english dictionary)
'''

#load the datasets into memory
examples, metadata = tfds.load('ted_hrlr_translate/pt_to_en', with_info=True,
        as_supervised=True)
train_examples, val_examples = examples['train'], examples['validation']

try:
    tokenizer_en = tfds.features.text.SubwordTextEncoder.load_from_file('tokenized_en')
except Exception as e:
    print("Creating tokenizers...")
    #create subword tokenizer to break words into subwords if they are not in the dictionary
    tokenizer_en = tfds.features.text.SubwordTextEncoder.build_from_corpus(
         (en.numpy() for pt, en in train_examples), target_vocab_size=2**13) #2**13
    tokenizer_en.save_to_file('tokenized_en')

try:
    tokenizer_pt = tfds.features.text.SubwordTextEncoder.load_from_file('tokenized_pt')
except Exception as e:
    print("Portuguese tokenizer being created...")
    #do the same for the portuguese language
    tokenizer_pt = tfds.features.text.SubwordTextEncoder.build_from_corpus(
        (pt.numpy() for pt, en in train_examples), target_vocab_size=2**13)
    tokenizer_pt.save_to_file('tokenized_pt')
'''
sample_string = 'Hello from over here!'

tokenized_string = tokenizer_en.encode(sample_string)
print('Tokenized string is {}'.format(tokenized_string))

original_string = tokenizer_en.decode(tokenized_string)
print('The original string: {}'.format(original_string))
#sanity check
assert original_string == sample_string

for ts in tokenized_string:
    print('{} ----> {}'.format(ts, tokenizer_en.decode([ts])))
'''
BUFFER_SIZE = 20000
BATCH_SIZE = 64

#add a start and end token to the input and target
def encode(lang1, lang2):
    lang1 = [tokenizer_pt.vocab_size] + tokenizer_pt.encode(
            lang1.numpy()) + [tokenizer_pt.vocab_size+1]

    lang2 = [tokenizer_en.vocab_size] + tokenizer_en.encode(
            lang2.numpy()) + [tokenizer_en.vocab_size+1]

    return lang1, lang2

#tf wrapper for encode, which passes regular tensors to the function. Need to do this as map() function (used later)
#only runs in graph mode, and .map is not a TF operation or function
def tf_encode(pt, en):
    result_pt, result_en = tf.py_function(encode, [pt, en], [tf.int64, tf.int64])
    result_pt.set_shape([None])
    result_en.set_shape([None])

    return result_pt, result_en


#filter function used to drop sequences of over 40 characters (for speed purposes)
MAX_LENGTH = 40
def filter_max_length(x, y, max_length=MAX_LENGTH):
    return tf.logical_and(tf.size(x) <= max_length,
            tf.size(y) <= max_length)

#want to map the filter_max_lenghth and encode() functions to all elements of the dataset
train_dataset = train_examples.map(tf_encode)
train_dataset = train_dataset.filter(filter_max_length)
#cache the dataset to memory to get a speedup while reading from it
train_dataset = train_dataset.cache()
train_dataset = train_dataset.shuffle(BUFFER_SIZE).padded_batch(BATCH_SIZE, padded_shapes=([None],[None])) ############CHECK THIS FOR POTENTIAL ERROR
#
#
#______________________________________________________________________________________
#
#
train_dataset = train_dataset.prefetch(tf.data.experimental.AUTOTUNE)

val_dataset = val_examples.map(tf_encode)
val_dataset = val_dataset.filter(filter_max_length).padded_batch(BATCH_SIZE, padded_shapes=([None],[None]))
pt_batch, en_batch = next(iter(val_dataset))
#print(pt_batch, en_batch)

#helper for positional_encoding()
def get_angles(pos, i, d_model):
    angle_rates = 1 / np.power(10000, (2 * (i//2)) / np.float32(d_model))
    return pos * angle_rates


#used to give information about the relative position
def positional_encoding(position, d_model):
    angle_rads = get_angles(np.arange(position)[:, np.newaxis],
            np.arange(d_model)[np.newaxis, :],
            d_model)

    #apply sin to even indices in the array; 2i
    angle_rads[:, 0::2] = np.sin(angle_rads[:, 0::2])

    #apply cos to odd indices in the array; 2i+1
    angle_rads[:, 1::2] = np.cos(angle_rads[:, 1::2])

    pos_encoding = angle_rads[np.newaxis, ...]

    return tf.cast(pos_encoding, dtype=tf.float32)

pos_encoding = positional_encoding(50, 512)
'''
print(pos_encoding.shape)

plt.pcolormesh(pos_encoding[0], cmap='RdBu')
plt.xlabel('Depth')
plt.xlim((0, 512))
plt.ylabel('Position')
plt.colorbar()
plt.show()
'''

#mask all the padding tokens in a sequence. Outputs a 1 a locations where a pad value is present, 0 otherwise
def create_padding_mask(seq):
    seq = tf.cast(tf.math.equal(seq, 0), tf.float32)

    #add extra dimensions to add the padding
    #to the attention logits
    return seq[:, tf.newaxis, tf.newaxis, :] # (batch_size, 1, 1, seq_len)

#used to mask the future values in the sequence
def create_look_ahead_mask(size):
    mask = 1 - tf.linalg.band_part(tf.ones((size, size)), -1, 0)
    return mask #(seq_len, seq_len)


'''
SCALED DOT PRODUCT ATTENTION
'''
def scaled_dot_product_attention(q, k, v, mask):
    ''' calculate the attention weights
    q,k,v must have matching leading dimensions
    k, v must have matching penultimate dimensions, i.e.: seq_len_k = seq_len_v
    The mask has different shapes depending on its type(padding or look ahead)
    but it must be broadcastable for addition

    Args:
        q: query shape == (..., seq_len_q, depth)
        k: key shape == (..., seq_len_k, depth)
        v: value shape == (..., seq_len_v, depth_v)
        mask: Float tensor with shape broadcastable to
            (..., seq_len_q, seq_len_k). Defaults to None.

    Returns:
        output, attention_weights
    '''

    matmul_qk = tf.matmul(q, k, transpose_b=True) #(..., sesq_len_q, seq_len_k)

    #scale matmul_qk
    dk = tf.cast(tf.shape(k)[-1], tf.float32)
    scaled_attention_logits = matmul_qk / tf.math.sqrt(dk)

    # add the mask to the scaled tensor
    if mask is not None:
        scaled_attention_logits += (mask * -1e9)

    #softmax is normalized on the last axis (seq_len_k) so that the scores add to 1
    #this also does normalization on K, so the values decide the amount of 
    #importance given to Q
    attention_weights = tf.nn.softmax(scaled_attention_logits, axis=-1) # (seq_len_q, seq_len_k)

    output = tf.matmul(attention_weights, v) # (..., seq_len_q, depth_v)

    #output represents multiplication of the attention weights and the V vector. 
    #words we want to focus on are kept and irrelevant words are flushed out
    return output, attention_weights

def print_out(q, k, v):
    temp_out, temp_attn = scaled_dot_product_attention(q, k, v, None)
    print('Attention weights are:')
    print(temp_attn)
    print('Output is:')
    print(temp_out)

'''
MULTI HEAD ATTENTION
'''
class MultiHeadAttention(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads):
        super(MultiHeadAttention, self).__init__()
        self.num_heads = num_heads
        self.d_model = d_model

        assert d_model % self.num_heads == 0

        self.depth = d_model // self.num_heads

        self.wq = tf.keras.layers.Dense(d_model)
        self.wk = tf.keras.layers.Dense(d_model)
        self.wv = tf.keras.layers.Dense(d_model)

        self.dense = tf.keras.layers.Dense(d_model)

    def split_heads(self, x, batch_size):
        # split the last dimension into (num_heads, depth)
        #transpose the result such that the shape is (batch_size, num_heads, seq_len, depth)

        x = tf.reshape(x, (batch_size, -1, self.num_heads, self.depth))
        return tf.transpose(x, perm=[0,2,1,3])

    def call(self, v, k, q, mask):
        batch_size = tf.shape(q)[0]

        q = self.wq(q) # (batch_size, seq_len, d_model)
        k = self.wk(k) # (batch_size, seq_len, d_model)
        v = self.wv(v) # (batch_size, seq_len, d_model)

        q = self.split_heads(q, batch_size) # (batch_size, num_heads, seq_len_q, depth)
        k = self.split_heads(k, batch_size) # (batch_size, num_heads, seq_len_k, depth)
        v = self.split_heads(v, batch_size) # (batch_size, num_heads, seq_len_v, depth)

        #scaled_attention.shape == (batch_size, num_heads, seq_len_q, depth) -- for reference
        #attention_weights.shape == (batch_size, num_heads, seq_len_q, seq_len_k) -- for ref.
        scaled_attention, attention_weights = scaled_dot_product_attention(q, k, v, mask)

        scaled_attention = tf.transpose(scaled_attention, perm=[0,2,1,3]) #(batch_size, seq_len_q, num_heads, depth)
        concat_attention = tf.reshape(scaled_attention, (batch_size, -1, self.d_model)) #(batch_size, seq_len_q, d_model)

        output = self.dense(concat_attention) # (batch_size, seq_len_q, d_model)
        return output, attention_weights

'''
#for testing
temp_mha = MultiHeadAttention(d_model=512, num_heads=8)
y = tf.random.uniform((1,60,512)) #(batch_size, encoder_sequence, d_model)
out, attn = temp_mha(y, k=y, q=y, mask=None)
print(out.shape, attn.shape)
'''

'''
POINT WISE FEED FORWARD NETWORK
'''
#consists of two point wise feed forward layers with ReLU activation inbetween
def point_wise_feed_forward_network(d_model, dff):
    return tf.keras.Sequential([
        tf.keras.layers.Dense(dff, activation='relu'), # (batch_size, seq_len, dff)
        tf.keras.layers.Dense(d_model) # (batch_size, seq_len, d_model
    ])

'''
ENCODER LAYER
'''
class EncoderLayer(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(EncoderLayer, self).__init__()
        
        #multi head attention layer
        self.mha = MultiHeadAttention(d_model, num_heads)
        #feed forward network layer
        self.ffn = point_wise_feed_forward_network(d_model, dff)

        #layer normalization
        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        #residual connections
        self.dropout1 = tf.keras.layers.Dropout(rate)
        self.dropout2 = tf.keras.layers.Dropout(rate)

    def call(self, x, training, mask):

        #each layer has a residual connection layer followed by layer normalization

        attn_output, _ = self.mha(x, x, x, mask) # (batch_size, input_seq_len, d_model)
        attn_output = self.dropout1(attn_output, training=training)
        out1 = self.layernorm1(x + attn_output) # (batch_size, input_seq_len, d_model)

        ffn_output = self.ffn(out1) # (batch_size, input seq_len, d_model)
        ffn_output = self.dropout2(ffn_output, training=training)
        out2 = self.layernorm2(out1 + ffn_output) # (batch_size, input_seq_len, d_model)

        return out2

'''
DECODER LAYER
'''

class DecoderLayer(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(DecoderLayer, self).__init__()

        self.mha1 = MultiHeadAttention(d_model, num_heads)
        self.mha2 = MultiHeadAttention(d_model, num_heads)

        self.ffn = point_wise_feed_forward_network(d_model, dff)

        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm3 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tf.keras.layers.Dropout(rate)
        self.dropout2 = tf.keras.layers.Dropout(rate)
        self.dropout3 = tf.keras.layers.Dropout(rate)

    def call(self, x, enc_output, training, look_ahead_mask, padding_mask):
        #enc_output.shape == (batch_size, input_seq_len, d_model)

        attn1, attn_weight_blocks1 = self.mha1(x, x, x, look_ahead_mask) #(batch_size, target_seq_len, d_model)
        attn1 = self.dropout1(attn1, training=training)
        out1 = self.layernorm1(attn1 + x)

        attn2, attn_weight_blocks2 = self.mha2(enc_output, enc_output, out1, padding_mask) #(batch_size, target_seq_len, d_model)
        attn2 = self.dropout2(attn2, training=training)
        out2 = self.layernorm2(attn2 + out1) #(batch_size, target_seq_len, d_model)

        ffn_output = self.ffn(out2) # (batch_size, target_seq_len, d_model)
        ffn_output = self.dropout3(ffn_output, training=training)
        out3 = self.layernorm3(ffn_output + out2) # (batch_size, target_seq_len, d_model)

        return out3, attn_weight_blocks1, attn_weight_blocks2

'''
#testing
sample_encoder_layer = EncoderLayer(512, 8, 2048)
sample_encoder_layer_output = sample_encoder_layer(tf.random.uniform((64,43,512)), False, None)


sample_decoder_layer = DecoderLayer(512, 8, 2048)
sample_decoder_layer_output, _, _ = sample_decoder_layer(
        tf.random.uniform((64, 50, 512)), sample_encoder_layer_output,
        False, None, None)
print(sample_decoder_layer_output.shape)
'''

'''
ACTUAL ENCODER
consists of 
1. Input embedding
2. Positional Encoding
3. N number of encoder layers
'''
class Encoder(tf.keras.layers.Layer):
    def __init__(self, num_layers, d_model, num_heads, dff, input_vocab_size, maximum_position_encoding, rate=0.1):
        super(Encoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers

        #input embedding
        self.embedding = tf.keras.layers.Embedding(input_vocab_size, d_model)
        #positional encoding
        self.pos_encoding = positional_encoding(maximum_position_encoding, self.d_model)

        #N encoder layers
        self.enc_layers = [EncoderLayer(d_model, num_heads, dff, rate)
                for _ in range(num_layers)]
        
        #residual connection(?)
        self.dropout = tf.keras.layers.Dropout(rate)

    def call(self, x, training, mask):
        
        seq_len = tf.shape(x)[1]

        #adding embedding and positional encoding
        x = self.embedding(x) # (batch_size, input_seq_len, d_model)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x += self.pos_encoding[:, :seq_len, :]

        x = self.dropout(x, training=training)

        for i in range(self.num_layers):
            x = self.enc_layers[i](x, training, mask)

        return x # (batch_size, input_seq_len, d_model)
'''
sample_encoder = Encoder(num_layers=2, d_model=512, num_heads=8, dff=2048, input_vocab_size=8500, maximum_position_encoding=10000)
temp_input = tf.random.uniform((64,62), dtype=tf.int64, minval=0, maxval=200)
sample_encoder_output = sample_encoder(temp_input, training=False, mask=None)

print(sample_encoder_output.shape)
'''



'''
ACTUAL DECODER
Consists of
1) Output embedding
2) Positional Encoding
3) N number of decoder layers
'''

class Decoder(tf.keras.layers.Layer):
    def __init__(self, num_layers, d_model, num_heads, dff, target_vocab_size, maximum_position_encoding, rate=0.1):
        super(Decoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers
        
        self.embedding = tf.keras.layers.Embedding(target_vocab_size, d_model)
        self.pos_encoding = positional_encoding(maximum_position_encoding, d_model)

        self.dec_layers = [DecoderLayer(d_model, num_heads, dff, rate)
                for _ in range(num_layers)]
        self.dropout = tf.keras.layers.Dropout(rate)

    def call(self, x, enc_output, training, look_ahead_mask, padding_mask):
        seq_len = tf.shape(x)[1]
        attention_weights = {}

        x = self.embedding(x) #(batch_size, target_seq_len, d_model)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x += self.pos_encoding[:, :seq_len, :]

        x = self.dropout(x, training=training)

        for i in range(self.num_layers):
            x, block1, block2 = self.dec_layers[i](x, enc_output, training, look_ahead_mask, padding_mask)

            attention_weights['decoder_layer{}_block1'.format(i+1)] = block1
            attention_weights['decoder_layer{}_block2'.format(i+1)] = block2

        #x.shape == (batch_size, target_seq_len, d_model)
        return x, attention_weights
'''
sample_decoder = Decoder(num_layers=2, d_model=512, num_heads=8, dff=2048, target_vocab_size=8000, maximum_position_encoding=5000)
temp_input = tf.random.uniform((64,26), dtype=tf.int64, minval=0, maxval=200)

output, attn = sample_decoder(temp_input, enc_output=sample_encoder_output, training=False, look_ahead_mask=None, padding_mask=None)

print(output.shape, attn['decoder_layer2_block2'].shape)
'''



'''
TRANSFORMER
Consists of encoder, decoder and a final linear layer. The output of the decoder is the input to the linear layer and its output is returned
'''

class Transformer(tf.keras.Model):
    def __init__(self, num_layers, d_model, num_heads, dff, input_vocab_size, target_vocab_size, pe_input, pe_target, rate=0.1):
        super(Transformer, self).__init__()

        self.encoder = Encoder(num_layers, d_model, num_heads, dff, input_vocab_size, pe_input, rate)
        self.decoder = Decoder(num_layers, d_model, num_heads, dff, target_vocab_size, pe_target, rate)
        self.final_layer = tf.keras.layers.Dense(target_vocab_size)

    def call(self, inp, tar, training, enc_padding_mask, look_ahead_mask, dec_padding_mask):
        enc_output = self.encoder(inp, training, enc_padding_mask) # (batch_size, inp_seq_len, d_model)

        #dec_output.shape == (batch_size, tar_seq_len, d_model)
        dec_output, attention_weights = self.decoder(tar, enc_output, training, look_ahead_mask, dec_padding_mask)

        final_output = self.final_layer(dec_output) #(batch_size, tar_seq_len, target_vocab_size)

        return final_output, attention_weights
'''
sample_transformer = Transformer(
        num_layers=2, d_model=512, num_heads=8, dff=2048, input_vocab_size=8500, target_vocab_size=8000, pe_input=10000, pe_target=6000)

temp_input = tf.random.uniform((64, 38), dtype=tf.int64, minval=0, maxval=200)
temp_target = tf.random.uniform((64, 36), dtype=tf.int64, minval=0, maxval=200)

fn_out, _ = sample_transformer(temp_input, temp_target, training=False,
        enc_padding_mask=None,
        look_ahead_mask=None,
        dec_padding_mask=None)

print(fn_out.shape) # (batch_size, tar_seq_len, target_vocab_size)
'''



'''
HYPERPARAMETERS
'''
num_layers = 4
d_model=128
dff=512
num_heads=8

input_vocab_size = tokenizer_pt.vocab_size + 2
target_vocab_size = tokenizer_en.vocab_size + 2
dropout_rate = 0.1

'''
OPTIMIZER
'''
class CustomSchedule(tf.keras.optimizers.schedules.LearningRateSchedule):
    def __init__(self, d_model, warmup_steps=4000):
        super(CustomSchedule, self).__init__()

        self.d_model = d_model
        self.d_model = tf.cast(self.d_model, tf.float32)

        self.warmup_steps = warmup_steps

    def __call__(self, step):
        arg1 = tf.math.rsqrt(step)
        arg2 = step * (self.warmup_steps ** -1.5)

        return tf.math.rsqrt(self.d_model) * tf.math.minimum(arg1, arg2)

learning_rate = CustomSchedule(d_model)

optimizer = tf.keras.optimizers.Adam(learning_rate, beta_1=0.9, beta_2=0.98, epsilon=1e-9)
temp_learning_rate_schedule = CustomSchedule(d_model)
'''
plt.plot(temp_learning_rate_schedule(tf.range(40000, dtype=tf.float32)))
plt.ylabel("Learning Rate")
plt.xlabel("Train Step")
plt.show()
'''



'''
LOSS AND METRICS
'''
loss_object = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction='none')

def loss_function(real, pred):
    mask = tf.math.logical_not(tf.math.equal(real, 0))
    loss_ = loss_object(real, pred)

    mask = tf.cast(mask, dtype=loss_.dtype)
    loss_ *= mask

    return tf.reduce_mean(loss_)

train_loss = tf.keras.metrics.Mean(name='train_loss')
train_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name='train_accuracy')

transformer = Transformer(num_layers, d_model, num_heads, dff, input_vocab_size,
        target_vocab_size, pe_input=input_vocab_size, pe_target=target_vocab_size,
        rate=dropout_rate)

def create_masks(inp, tar):
    #Encoder padding mask
    enc_padding_mask = create_padding_mask(inp)

    #Used in the 2nd attention block in the decoder
    #This padding mask is used to mask the encoder outputs
    dec_padding_mask = create_padding_mask(inp)

    #used in the 1st attention block in the decoder
    #it is used to pad and mask future tokens in the input received by the decoder
    look_ahead_mask = create_look_ahead_mask(tf.shape(tar)[1])
    dec_target_padding_mask = create_padding_mask(tar)
    combined_mask = tf.maximum(dec_target_padding_mask, look_ahead_mask)

    return enc_padding_mask, combined_mask, dec_padding_mask

#create the checkpoint path and the checkpoint manager. This will be used to save checkpoints ever N epochs
checkpoint_path = "./checkpoints/train"

ckpt = tf.train.Checkpoint(transformer=transformer, optimizer=optimizer)

ckpt_manager = tf.train.CheckpointManager(ckpt, checkpoint_path, max_to_keep=5)

#if a checkpoint exists, restore the latest checkpoint
if ckpt_manager.latest_checkpoint:
    ckpt.restore(ckpt_manager.latest_checkpoint)
    print('Latest checkpoint restored!!')

EPOCHS = 20

# The @tf.function trace-compiles train_step into a TF graph for faster
# exection. The function specializes to the precise shape of the argument
# tensors. To avoid re-tracing due to the variable sequence lengths or variable
# batch sizes ( the last batch is smaller), use input_signature to specify
# more generic shapes.

train_step_signature = [
        tf.TensorSpec(shape=(None, None), dtype=tf.int64),
        tf.TensorSpec(shape=(None, None), dtype=tf.int64),
]

@tf.function(input_signature=train_step_signature)
def train_step(inp, tar):
    tar_inp = tar[:, :-1]
    tar_real = tar[:, 1:]

    enc_padding_mask, combined_mask, dec_padding_mask = create_masks(inp, tar_inp)

    with tf.GradientTape() as tape:
        predictions, _ = transformer(inp, tar_inp,
                True,
                enc_padding_mask,
                combined_mask,
                dec_padding_mask)
        loss = loss_function(tar_real, predictions)
    gradients = tape.gradient(loss, transformer.trainable_variables)
    optimizer.apply_gradients(zip(gradients, transformer.trainable_variables))
    train_loss(loss)
    train_accuracy(tar_real, predictions)

'''
TRAIN THE DATA
'''

'''
#portuguese is used as the input language and english as the target language
for epoch in range(EPOCHS):
    start = time.time()

    train_loss.reset_states()
    train_accuracy.reset_states()

    #inp -> portuguese, tar -> english
    for (batch, (inp, tar)) in enumerate(train_dataset):
        train_step(inp, tar)

        if batch % 50 == 0:
            print ('Epoch {} Batch {} Loss {:.4f} Accuracy {:.4f}'.format(
                epoch + 1, batch, train_loss.result(), train_accuracy.result()))
    if(epoch + 1) % 5 == 0:
        ckpt_save_path = ckpt_manager.save()
        print('Saving checkpoint for epoch {} at {}'.format(epoch+1, ckpt_save_path))

    print('Epoch {} Loss {:.4f} Accuracy {:.4f}'.format(epoch+1, train_loss.result(), train_accuracy.result()))

    print('Time taken for 1 epoch: {} secs\n'.format(time.time() - start))
'''

def evaluate(inp_sentence):
    start_token = [tokenizer_pt.vocab_size]
    end_token = [tokenizer_pt.vocab_size + 1]

    #inp seq is portuguese, hence adding the start and end token
    inp_sentence = start_token + tokenizer_pt.encode(inp_sentence) + end_token
    encoder_input = tf.expand_dims(inp_sentence, 0)

    #as the target is english, the first word to the transformer should be the 
    #english start token
    decoder_input = [tokenizer_en.vocab_size]
    output = tf.expand_dims(decoder_input, 0)

    for i in range(MAX_LENGTH):
        enc_padding_mask, combined_mask, dec_padding_mask = create_masks(encoder_input, output)

        #predictions.shape == (batch_size, seq_len, vocab_size)
        predictions, attention_weights = transformer(encoder_input,
                output,
                False,
                enc_padding_mask,
                combined_mask,
                dec_padding_mask)

        #select the last word from the seq_len dimension
        predictions = predictions[: ,-1:, :] # (batch_size, 1, vocab_size)

        predicted_id = tf.cast(tf.argmax(predictions, axis=-1), tf.int32)

        #return the result if the predicted_id is equal to the end token
        if predicted_id == tokenizer_en.vocab_size+1:
            return tf.squeeze(output, axis=0), attention_weights

        #concatenate the predicted_id to the output which is given to the decoder as input
        output = tf.concat([output, predicted_id], axis=-1)

    return tf.squeeze(output, axis=0), attention_weights

def plot_attention_weights(attention, sentence, result, layer):
    fig = plt.figure(figsize=(16,8))

    sentence = tokenizer_pt.encode(sentence)

    attention = tf.squeeze(attention[layer], axis=0)

    for head in range(attention.shape[0]):
        ax = fig.add_subplot(2,4,head+1)

        #plot the attention weights
        ax.matshow(attention[head][:-1, :], cmap='viridis')

        fontdict = {'fontsize': 10}

        ax.set_xticks(range(len(sentence)+2))
        ax.set_yticks(range(len(result)))

        ax.set_ylim(len(result)-1.5, -0.5)

        ax.set_xticklabels(
                ['<start>']+[tokenizer_pt.decode([i]) for i in sentence]+['<end>'],
                fontdict=fontdict, rotation=90)

        ax.set_yticklabels([tokenizer_en.decode([i]) for i in result
            if i < tokenizer_en.vocab_size],
            fontdict=fontdict)

        ax.set_xlabel('Head {}'.format(head+1))

    plt.tight_layout()
    plt.show()

def translate(sentence, plot=''):
    result, attention_weights = evaluate(sentence)

    predicted_sentence = tokenizer_en.decode([i for i in result
        if i < tokenizer_en.vocab_size])

    print('Input: {}'.format(sentence))
    print('Predicted translation: {}'.format(predicted_sentence))

    if plot:
        plot_attention_weights(attention_weights, sentence, result, plot)

translate("os meus vizinhos ouviram sobre esta ideia", plot='decoder_layer4_block2')
print("Real translation: my neighboring home heard about this idea.")