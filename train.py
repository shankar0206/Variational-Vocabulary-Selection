import argparse
import tensorflow as tf
from data_utils import *
from sklearn.model_selection import train_test_split
from cnn_models.models import WordCNN, CharCNN, WordRNN
import math
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=str, default="word_cnn",
                    help="word_cnn | char_cnn | vd_cnn | word_rnn | att_rnn | rcnn")
parser.add_argument("--id", type=str, default="word_cnn")
parser.add_argument("--type", type=str, default="cross_entropy")
parser.add_argument("--variational", default=False, action="store_true")
parser.add_argument("--cutoff", type=int, default=1000)
parser.add_argument("--l1", default=False, action="store_true")
parser.add_argument("--dataset", default="dbpedia", type=str, help="dbpedia|ag_news|amazon_review_full|yahoo_answers|sogou_news|yelp_review_full")
parser.add_argument("--compress", default=False, action="store_true")
parser.add_argument("--evaluate", default=False, action="store_true")
parser.add_argument("--threshold", default=3, type=float)
parser.add_argument("--subword", default=False, action="store_true")
parser.add_argument("--emb_size", default=256, type=int)

args = parser.parse_args()

def build_dataset(dataset, word_dict=None, char=False):
    if 'dbpedia' in dataset:
        NUM_CLASS = 14
    elif 'ag_news' in dataset:
        NUM_CLASS = 4
    elif 'amazon_review' in dataset:
        NUM_CLASS = 5
    elif 'sogou_news' in dataset:
        NUM_CLASS = 5
    elif 'yahoo_answers' in dataset:
        NUM_CLASS = 10
    elif 'yelp_review' in dataset:
        NUM_CLASS = 5
    else:
        raise ValueError("No such dataset")

    if not char:
        if word_dict is None:
            if args.subword:
                word_dict = build_word_dict_cutoff(dataset, cutoff=None, tokenize=False)
            else:
                word_dict = build_word_dict_cutoff(dataset, cutoff=args.cutoff)
            file_name = "train_data_cuoff{}.pkl".format(args.cutoff)
        
        x, y = build_word_dataset(dataset, "train", word_dict, WORD_MAX_LEN, tokenize=not args.subword)
        print("Finished builiding the dataset")
        vocabulary_size = len(word_dict)
    else:
        x, y, alphabet_size = build_char_dataset(dataset, "train", "char_cnn", CHAR_MAX_LEN)
        print("Finished builiding the character dataset")
        vocabulary_size = alphabet_size

    if not args.compress:
        train_x, valid_x, train_y, valid_y = train_test_split(x, y, test_size=0.15)
    else:
        train_x, valid_x, train_y, valid_y = None, None, None, None

    if not char:
        test_x, test_y = build_word_dataset(dataset, "test", word_dict, WORD_MAX_LEN, tokenize=not args.subword)
    else:
        test_x, test_y, _ = build_char_dataset(dataset, "test", "char_cnn", CHAR_MAX_LEN)

    return train_x, valid_x, test_x, train_y, valid_y, test_y, word_dict, NUM_CLASS, vocabulary_size

def get_decay_rate(epoch):
    if "char" in args.model:
        return 0, 1e-3
    else:  
        if args.l1:
            return 1e-6, 1e-2
        elif args.variational:
            small_decay = 1e-5
            large_deacy = 1e-3
            start_decay = 40
            interval = (large_deacy - small_decay) / (NUM_EPOCHS - start_decay)
            if epoch < start_decay:
                cur_decay = small_decay
                learning_rate = 1e-2
            else:
                cur_decay = interval * (epoch - small_decay) + small_decay
                learning_rate = 1e-2
            return cur_decay, learning_rate
        else:
            return 0, 1e-2

BATCH_SIZE = 256
NUM_EPOCHS = 200
if args.subword:
    WORD_MAX_LEN = 300
else:
    WORD_MAX_LEN = 100
CHAR_MAX_LEN = 1014
DECAY_EVERY = 20

if "char" in args.model:
    train_x, valid_x, test_x, train_y, valid_y, test_y, word_dict, NUM_CLASS, vocabulary_size = build_dataset(args.dataset, char=True)
else:
    train_x, valid_x, test_x, train_y, valid_y, test_y, word_dict, NUM_CLASS, vocabulary_size = build_dataset(args.dataset, char=False)

print("Building dataset...")

if args.model == "word_cnn":
    filter_sizes = [3, 4, 5]
    with tf.variable_scope("model"):
        model = WordCNN(vocabulary_size, WORD_MAX_LEN, NUM_CLASS, emb_size=args.emb_size, is_training=True, filter_sizes=filter_sizes, 
            variational=args.variational, l1=args.l1, batch_size=BATCH_SIZE, compress=args.compress)
    with tf.variable_scope("model", reuse=tf.AUTO_REUSE):
        test_model = WordCNN(vocabulary_size, WORD_MAX_LEN, NUM_CLASS, emb_size=args.emb_size, is_training=False, filter_sizes=filter_sizes, 
            variational=args.variational, l1=args.l1, batch_size=BATCH_SIZE, compress=args.compress)
elif args.model == "char_cnn":
    with tf.variable_scope("model"):
        model = CharCNN(vocabulary_size, CHAR_MAX_LEN, NUM_CLASS, num_filters=args.emb_size, is_training=True)
    with tf.variable_scope("model", reuse=tf.AUTO_REUSE):
        test_model = CharCNN(vocabulary_size, CHAR_MAX_LEN, NUM_CLASS, num_filters=args.emb_size, is_training=False)
elif args.model == "word_rnn":
    with tf.variable_scope("model"):
        model = WordRNN(vocabulary_size, WORD_MAX_LEN, NUM_CLASS, emb_size=args.emb_size, is_training=True, num_hidden=args.emb_size,
            variational=args.variational, l1=args.l1, batch_size=BATCH_SIZE, compress=args.compress)
    with tf.variable_scope("model", reuse=tf.AUTO_REUSE):
        test_model = WordRNN(vocabulary_size, WORD_MAX_LEN, NUM_CLASS, emb_size=args.emb_size, is_training=False, num_hidden=args.emb_size,
            variational=args.variational, l1=args.l1, batch_size=BATCH_SIZE, compress=args.compress)
else:
    raise NotImplementedError()

with tf.Session() as sess:
    sess.run(tf.global_variables_initializer())
    variables_to_restore = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)
    saver = tf.train.Saver(variables_to_restore)

    if args.variational:
        model_folder = "{}_models/{}_{}_variational".format(args.dataset, args.id, args.emb_size)
    elif args.l1:
        model_folder = "{}_models/{}_{}_l1".format(args.dataset, args.id, args.emb_size)
    else:
        model_folder = "{}_models/{}_{}".format(args.dataset, args.id, args.emb_size)
    model_name = os.path.join(model_folder, "model.ckpt")
    
    if tf.train.checkpoint_exists(model_folder):
        saver.restore(sess, model_name)
        print('Restored on Test: {}'.format(model_name))
    
    if args.evaluate:
        if "char" in args.model:
            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt, inf_time = 0, 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch
                }
                start_time = time.time()           
                accuracy = sess.run(test_model.accuracy, feed_dict=valid_feed_dict)
                inf_time += time.time() - start_time
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            whole_size = sum([tf.size(_) for _ in variables_to_restore])
            print("Accuracy = {} with vocabulary {} inference used {} for model size {}".format(test_accuracy, vocabulary_size, inf_time, sess.run(whole_size)))
        elif args.subword:
            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt, inf_time = 0, 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch
                }
                start_time = time.time()           
                accuracy = sess.run(test_model.accuracy, feed_dict=valid_feed_dict)
                inf_time += time.time() - start_time
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            whole_size = sum([tf.size(_) for _ in variables_to_restore])
            print("Accuracy = {} with vocabulary {} inference used {} for model size {}".format(test_accuracy, vocabulary_size, inf_time, sess.run(whole_size)))
        elif args.variational:
            #for t in np.linspace(-3, 3, 10):
            mask, emb, ratios = sess.run([model.mask, model.embedding.embedding_mean, model.embedding.embedding_logdropout_ratio], feed_dict={model.threshold: args.threshold})
            word_idict = {i:x for x,i in word_dict.iteritems()}
            new_word_dict = {"<pad>": 0, "<unk>": 1, "<eos>": 2}
            emb_mean = [emb[0], emb[1], emb[2]]
            emb_logdropout_ratio = [0, 0, 0]
            for i in range(3, vocabulary_size):
                if mask[i, 0] > 0:
                    new_word_dict[word_idict[i]] = len(new_word_dict)
                    emb_mean.append(emb[i])
                    emb_logdropout_ratio.append(ratios[i])
            new_vocabulary_size = len(emb_mean)
            emb_mean = np.vstack(emb_mean)
            emb_logdropout_ratio = np.vstack(emb_logdropout_ratio)
            new_train_x, new_valid_x, new_test_x, new_train_y, new_valid_y, new_test_y, _, _, _ = build_dataset(args.dataset, new_word_dict)
            with tf.variable_scope("new_model", reuse=tf.AUTO_REUSE):
                new_test_model = WordCNN(new_vocabulary_size, WORD_MAX_LEN, NUM_CLASS, emb_size=args.emb_size, is_training=False, variational=False, l1=False, batch_size=BATCH_SIZE, compress=args.compress)
            new_variables_to_restore = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope="new_model")
            init_ops = []
            for v in new_variables_to_restore:
                if v.op.name == "new_model/embedding":
                    init_ops.append(tf.assign(v, emb_mean))
                elif v.op.name ==  "new_model/embedding_ratio":
                    init_ops.append(tf.assign(v, emb_logdropout_ratio))
                else:
                    for v1 in variables_to_restore:
                        if v.op.name.split('/')[1:] == v1.op.name.split('/')[1:]:
                            init_ops.append(tf.assign(v, v1))

            for _ in init_ops:
                sess.run(_)

            valid_batches = batch_iter(new_test_x, new_test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt, inf_time = 0, 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    new_test_model.x: valid_x_batch,
                    new_test_model.y: valid_y_batch
                }
                start_time = time.time()            
                accuracy = sess.run(new_test_model.accuracy, feed_dict=valid_feed_dict)
                inf_time += time.time() - start_time
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            whole_size = sum([tf.size(_) for _ in new_variables_to_restore])
            print("Accuracy = {} with vocabulary {} inference used {} for model size {}".format(test_accuracy, len(new_word_dict), inf_time, sess.run(whole_size)))

        sys.exit(1)

    #compressed = [word_dict[_] for _ in mask]

    if args.compress and args.variational:
        vocab = []
        metrics = []
        #log_dropout = sess.run(test_model.embedding.embedding_logdropout_ratio)
        intervals = np.linspace(-10, 10, 100)
        for t in intervals:
            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt = 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch,
                    test_model.threshold: t
                }
                accuracy = sess.run(test_model.accuracy, feed_dict=valid_feed_dict)
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            sparsity = sess.run(test_model.sparsity, feed_dict={test_model.threshold:t})
            #print("Accuracy = {} with vocabulary {}".format(test_accuracy, (1 - sparsity) * len(word_dict)))
            rest_words = (1 - sparsity) * len(word_dict)
            if rest_words > 1:
                metrics.append(test_accuracy)
                vocab.append(rest_words)
        print metrics
        print vocab
        print("ROC={}".format(ROC(metrics, vocab)))
        sys.exit(1)
    elif args.compress and args.l1:
        vocab = []
        metrics = []
        norms = sess.run(model.embedding.rowwise_norm())
        intervals = np.linspace(norms.max(), norms.min(), 100)
        #intervals = np.linspace(1e-8, 1, 90) + np.linspace(2, 20, 10)
        for t in intervals:
            zeros = np.zeros((vocabulary_size, 1), 'float32')
            zeros[:int(t), :] = 1
            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt = 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch,
                    test_model.l1_threshold: t
                }
                accuracy = sess.run(test_model.accuracy, feed_dict=valid_feed_dict)
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            sparsity = sess.run(test_model.sparsity, feed_dict={test_model.l1_threshold:t})
            rest_words = (1 - sparsity) * len(word_dict)
            if rest_words > 1:
                metrics.append(test_accuracy)
                vocab.append(rest_words)
        print metrics
        print vocab
        print("ROC={}".format(ROC(metrics, vocab)))        
        sys.exit(1)
    elif args.compress:
        vocab = []
        metrics = []
        t = 5000
        for _ in range(50):
            zeros = np.zeros((vocabulary_size, 1), 'float32')
            idxs = np.random.choice(range(0, 10000), size=t)
            zeros[idxs, :] = 1
            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt = 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch,
                    test_model.mask: zeros
                }
                accuracy = sess.run(test_model.accuracy, feed_dict=valid_feed_dict)
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt
            #if rest_words > 1:
            metrics.append(test_accuracy)
            vocab.append(t)
        print metrics
        print vocab
        print("ROC={}".format(ROC(metrics, vocab)))        
        sys.exit(1)


    train_batches = batch_iter(train_x, train_y, BATCH_SIZE, NUM_EPOCHS, test=False)
    num_batches_per_epoch = (len(train_x) - 1) // BATCH_SIZE + 1
    max_accuracy = 0
    
    if not os.path.exists(model_folder):
        os.mkdir(model_folder)
    f = open(os.path.join(model_folder, "training.log"), "w")
    for epochs, x_batch, y_batch in train_batches:        
        cur_decay, learning_rate = get_decay_rate(epochs)
        train_feed_dict = {
            model.x: x_batch,
            model.y: y_batch,
            model.weight_decay: cur_decay,
            model.learning_rate: learning_rate,
            model.threshold: 3.0,
            model.l1_threshold: 1e-4
        }

        if args.variational:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)
        elif args.l1:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)
        else:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)

        if step % 100 == 0:
            print("epoch {0}: KL_decay {1}: step {2}: cross_entropy = {3}: reg_loss = {4}, sparsity = {5}: full_vocab = {6}: remaining_vocab: {7}".format(epochs, cur_decay, step, loss, reg_loss, sparsity, vocabulary_size, int((1 - sparsity) * vocabulary_size)))

        if step % 2000 == 0:
            # Test accuracy with validation data for each epoch.
            valid_batches = batch_iter(valid_x, valid_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt = 0, 0

            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch,
                    test_model.threshold: 3.0,
                    test_model.l1_threshold: 1e-4
                }
                accuracy, predictions = sess.run([test_model.accuracy, test_model.predictions], feed_dict=valid_feed_dict)
                sum_accuracy += accuracy
                cnt += 1
            valid_accuracy = sum_accuracy / cnt

            valid_batches = batch_iter(test_x, test_y, BATCH_SIZE, 1, test=True)
            sum_accuracy, cnt = 0, 0
            for epochs, valid_x_batch, valid_y_batch in valid_batches:
                valid_feed_dict = {
                    test_model.x: valid_x_batch,
                    test_model.y: valid_y_batch,
                    test_model.threshold: 3.0,
                    test_model.l1_threshold: 1e-4
                }
                accuracy, sparsity = sess.run([test_model.accuracy, test_model.sparsity], feed_dict=valid_feed_dict)
                sum_accuracy += accuracy
                cnt += 1
            test_accuracy = sum_accuracy / cnt

            print("\nValidation Accuracy = {1} Test Accuracy = {2} Vocabulary = {3}\n".format(step // num_batches_per_epoch, valid_accuracy, test_accuracy, int((1 - sparsity) * vocabulary_size)))
            print >> f, "Validation Accuracy = {1} Test Accuracy = {2} Vocabary = {3}".format(step // num_batches_per_epoch, valid_accuracy, test_accuracy, int((1 - sparsity) * vocabulary_size))
            
            # Save model
            if test_accuracy > max_accuracy:
                max_accuracy = valid_accuracy
                saver.save(sess, model_name)
                print("Model is saved with sparsity \n")

    f.close()
