# coding:utf8

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import time
import sys
sys.path.append('/Users/imperatore/PycharmProjects/question-recognition/')
from recognition.kernel.data_provider import *
import shutil
from tensorflow.python.keras.layers import *

from tensorflow.python import debug as tf_debug

DIGITS = '0123456789'
# characters = '0123456789+-*/=()'
characters = '0123456789'
width, height, n_class = 280, 48, len(characters) + 1
import datetime


class CRNN():
  """

  """

  def __init__(self, num_class, input_shape):
    """
    Initialize features, labels, configurations, batch_size, num_class and keep probability.
    Args:
      num_class: =categories + 1
      input_batch: features
      sparse_target_batch: labels
      seqlen_batch: sequence length
    """
    self.num_class = num_class  # =categories + 1
    self.interval_loss = 100
    self.FLAGS = tf.flags.FLAGS
    self.batch_size = self.FLAGS.batch_size
    self.input_shape = input_shape
    self.graph = tf.Graph()
    with self.graph.as_default():
      with tf.name_scope(name='ph'):
        # Read data with generator
        self.X = tf.placeholder(tf.float32, shape=input_shape, name='x')
        self.y = tf.sparse_placeholder(tf.int32, name='y')  # 不指定shape时，可以feed任意shape
        self.seq_len = tf.placeholder(tf.int32, [None], name='seq_len')
        self.keep_prob = tf.placeholder(tf.float32, name='kp')

  def _change_size(self, input_shape, channel=None, auto_change_channel=True):
    """
    变换特征图尺寸，CNN中使用
    Args:
      input_shape:
      channel:
      auto_change_channel:
    :return: 改变后的尺寸
    """
    input_shape[2] = input_shape[3]
    if auto_change_channel:
      input_shape[3] = input_shape[3] * 2
    if channel:
      input_shape[3] = channel
    return input_shape

  def _init_variable(self, shape, name=None, zero=None):
    """
    Create and initialize tensorflow variable.
    Args:
        shape: A 1-D integer Tensor or Python array. The shape of the initiated variable.
        name: A string. The name in tensorflow graph of the initiated variable.
    Return: A variable.
    """
    if not zero:
      return tf.Variable(tf.random_uniform(shape, 0., 1.), name=name)
    else:
      return tf.Variable(tf.zeros(shape, dtype=tf.float32), name=name)

  def image2head(self, x):
    with tf.name_scope('image2head'):
      for i in range(4):
        # 2 convolution layers
        x = tf.nn.conv2d(x, eval('self.w%s0' % i), [1, 1, 1, 1],
                         padding='SAME', name='cnn0%s' % i)
        self.__dict__['b%s0' % i] = self._init_variable([x.get_shape().as_list()[3], ], name='b_%s0' % i, zero=True)
        tf.nn.bias_add(x, self.__dict__['b%s0' % i])

        x = tf.layers.batch_normalization(x, name='bn0%s' % i)
        tf.nn.relu(x)

        x = tf.nn.conv2d(x, eval('self.w%s1' % i), [1, 1, 1, 1],
                         padding='SAME', name='cnn1%s' % i)
        self.__dict__['b%s1' % i] = self._init_variable([x.get_shape().as_list()[3], ], name='b_%s1' % i, zero=True)
        tf.nn.bias_add(x, self.__dict__['b%s1' % i])

        x = tf.layers.batch_normalization(x, name='bn1%s' % i)
        tf.nn.relu(x)

        print('Use the kernel:', eval('self.w%s0' % i), eval('self.w%s1' % i))

        x = tf.nn.max_pool(x, [1, 2, 2, 1], strides=[1, 2, 2, 1],
                           padding='VALID', name='cnn2%s' % i)
      return x

  def head2tail(self, x):
    with tf.name_scope('head2tail'):
      self.rnn_units = self.FLAGS.rnn_units
      shape = x.get_shape().as_list()
      x = tf.reshape(x, shape=[-1, shape[1], shape[2] * shape[3]])
      self.w0 = self._init_variable(shape=[shape[2] * shape[3], self.rnn_units], name='w0')
      self.b0 = self._init_variable(shape=[self.rnn_units, ], name='b0', zero=True)
      # x = tf.nn.xw_plus_b(x, self.w0, self.b0, name='dense0')
      # x = tf.einsum('ijk,kl->ijl', x, self.w0, name='dense0')
      x = tf.tensordot(x, self.w0, axes=[[2], [0]], name='tensordot0')
      x = tf.add(x, self.b0)

      x = tf.layers.batch_normalization(x, name='bn2')
      x = tf.nn.relu(x)

      # 构建双向GRU
      gru0 = GRU(self.rnn_units, activation='tanh',
                 return_sequences=True, kernel_initializer='he_uniform',
                 name='gru0')(x)

      gru0b = GRU(self.rnn_units, activation='tanh',
                  return_sequences=True, kernel_initializer='he_uniform',
                  name='gru0b', go_backwards=True)(x)

      x = tf.concat([gru0, gru0b], axis=-1, name='tanh')
      # x = tf.add(gru0, gru0b, name='concat')

      gru1 = GRU(self.rnn_units, activation='tanh',
                 return_sequences=True, kernel_initializer='he_uniform',
                 name='gru1')(x)

      gru1b = GRU(self.rnn_units, activation='tanh',
                  return_sequences=True, kernel_initializer='he_uniform',
                  name='gru1b', go_backwards=True)(x)

      x = tf.add(gru1, gru1b, name='add')

      x = tf.nn.dropout(x, keep_prob=self.keep_prob, name='dropout_tail')

      # self.w1 = self._init_variable(shape=[self.rnn_units * 2, self.num_class], name='w1')
      self.w1 = self._init_variable(shape=[self.rnn_units, self.num_class], name='w1')
      self.b1 = self._init_variable(shape=[self.num_class, ], name='b1', zero=True)
      # x = tf.nn.xw_plus_b(x, self.w1, self.b1, name='dense1')
      # x = tf.einsum('ijk,kl->ijl', x, self.w1)
      x = tf.tensordot(x, self.w1, axes=[[2], [0]], name='tesnordot1')
      x = tf.add(x, self.b1)
      x = tf.nn.softmax(x, name='bottom_softmax')

      # time major 模式需要的input shape:(max_time x batch_size x num_classes)
      x = tf.transpose(x, (1, 0, 2))

    return x

  def _build_network(self, mode='train'):
    """
    构建整个网络
    Args:
      input_shape:
      mode:

    Returns:

    """
    # 定义CNN kernels
    kernel_shape = [3, 3, 1, 32]
    self.w00 = self._init_variable(kernel_shape, name='conv_w00')
    for i in range(5):
      for j in range(2):
        if i == 0 and j == 0:
          continue
        auto_change_channel = True if j < 1 else False
        kernel_shape = self._change_size(kernel_shape, auto_change_channel=auto_change_channel)
        self.__dict__['w%s%s' % (i, j)] = self._init_variable(kernel_shape, name='conv_w%s%s' % (i, j))
        print('w%s%s' % (i, j), eval('self.w%s%s.shape' % (i, j)))

    self.head = self.image2head(self.X)
    # self.head = self.X
    self.output = self.head2tail(self.head)  # self.output == self.tail

  def architecture(self, mode='train'):
    # 构建图
    with self.graph.as_default():

      config = tf.ConfigProto(
        allow_soft_placement=self.FLAGS.allow_soft_placement,  # 设置让程序自动选择设备运行
        log_device_placement=self.FLAGS.log_device_placement)

      self.sess = tf.Session(config=config)
      # self.sess = tf_debug.LocalCLIDebugWrapperSession(self.sess)

      self._build_network(mode=mode)

      with tf.name_scope('loss'):
        # 计算误差
        #  time_major默认为True
        print('output shape:', self.output.shape)
        print('label  shape:', self.y.dense_shape)
        print('seqlen shape:', self.seq_len.shape)
        self.output = tf.math.log(self.output + 1e-7)

        self.loss = tf.nn.ctc_loss(labels=self.y, inputs=self.output,
                                   sequence_length=self.seq_len)
        self.cost = tf.reduce_mean(self.loss, name='reduce_mean')

      with tf.name_scope('step'):
        self.global_step = tf.Variable(0, name='global_step')
        # self.learning_rate = tf.train.exponential_decay(self.FLAGS.INITIAL_LEARNING_RATE,
        #                                                 self.global_step,
        #                                                 self.FLAGS.DECAY_STEPS,
        #                                                 self.FLAGS.LEARNING_RATE_DECAY_FACTOR,
        #                                                 staircase=False)
        self.learning_rate = self.FLAGS.INITIAL_LEARNING_RATE
      with tf.name_scope('gradients'):
        self.optimizer = tf.train.AdamOptimizer(self.learning_rate, name='adam_optimizer')
        self.grads_and_vars = self.optimizer.compute_gradients(self.loss)
        self.train_op = self.optimizer.apply_gradients(self.grads_and_vars, self.global_step, name='finally_update')

      # ===至此,模型构建完成=========================================

      with tf.name_scope('accuracy'):
        # time_major默认为True
        # beam search decoder
        self.decoded, self.log_prob = tf.nn.ctc_beam_search_decoder(self.output, self.seq_len,
                                                                    merge_repeated=False, top_paths=1)
        # greedy decoder
        # self.decoded, self.log_prob = tf.nn.ctc_greedy_decoder(self.output, self.seq_len)

        concat_indices = None
        concat_values = None
        # accelerate_indices = 0

        for i in range(len(self.decoded)):
          decoded = self.decoded[i]
          if i == 0:
            concat_indices = decoded.indices
            concat_values = decoded.values
          # else:
          #   print('拼接一把')
          #   decoded_indices = tf.concat([tf.expand_dims(decoded.indices[:, 0] + accelerate_indices, axis=-1),
          #                                tf.expand_dims(decoded.indices[:, 1], axis=-1)], axis=1)
          #   concat_indices = tf.concat([concat_indices, decoded_indices], axis=0)
          #   concat_values = tf.concat([concat_values, decoded.values], axis=0)
          # accelerate_indices += decoded.shape[0]

        first_dim = self.FLAGS.batch_size
        second_dim = tf.reduce_max(self.seq_len)

        concat_values = tf.cast(concat_values, tf.int32)

        print('Informations  \noutput:{}\ndecoded:{},\nseq_len:{},'
              '\nconcat_indices:{},\nconcat_values:{}'
              .format(self.output, self.decoded, self.seq_len, concat_indices, concat_values))
        print('first dimension:{},\nsecond dimension:{}'.format(first_dim, second_dim))

        decoded_tensor = tf.SparseTensor(indices=concat_indices, values=concat_values,
                                         dense_shape=[first_dim, second_dim])

        # 使用编辑距离计算准确率
        edit_distance = tf.edit_distance(decoded_tensor, self.y, name='edit_distance', normalize=True)
        self.acc_op = tf.subtract(tf.constant(1, dtype=tf.float32), tf.reduce_mean(edit_distance), name='subtract')

      # 开始记录信息
      self.summary()

      self.sess.run(tf.global_variables_initializer())

      # with self.sess.as_default():
      # [print(n.name) for n in tf.get_default_graph().as_graph_def().node]

  def calc_accuracy(self, decode_list, test_target):
    original_list = decode_sparse_tensor(test_target)
    detected_list = decode_sparse_tensor(decode_list)
    # detected_list = self.sess.run(tf.sparse_to_dense(decode_list))
    true_numer = 0

    if len(original_list) != len(detected_list):
      print("len(original_list)", len(original_list), "len(detected_list)", len(detected_list),
            " test and detect length desn't match")
      return
    print("T/F: original(length) <-------> detected(length)")
    for idx, number in enumerate(original_list):
      detect_number = detected_list[idx]
      hit = (number == detect_number)
      print(hit, number, "(", len(number), ") <-------> ", detect_number, "(", len(detect_number), ")")
      if hit:
        true_numer = true_numer + 1
    print("Test Accuracy:", true_numer * 1.0 / len(original_list))

  def _accuracy(self, test_inputs, test_targets, test_seq_len):
    # test_inputs, test_targets, test_seq_len = get_next_batch(self.FLAGS.batch_size)
    # test_inputs, test_targets, test_seq_len = get_next_batch(1)
    print('test sequence length:', test_seq_len)
    decoded, log_prob = tf.nn.ctc_beam_search_decoder(self.output,
                                                      test_seq_len,
                                                      merge_repeated=False)

    # decoded, log_prob = tf.nn.ctc_greedy_decoder(self.output,
    #                                              test_seq_len)

    test_feed = {self.keep_prob: 1.,
                 self.X: test_inputs,
                 self.y: test_targets,
                 self.seq_len: test_seq_len}

    dd, log_probs = self.sess.run([decoded[0], log_prob],
                                  feed_dict=test_feed)
    self.calc_accuracy(dd, test_targets)

  def summary(self):
    """

    Returns:

    """
    timestamp = str(int(time.time()))
    out_dir = os.path.abspath(os.path.join(os.path.curdir, '../../', 'run_temp', timestamp))
    print('Writing to {}\n'.format(out_dir))

    # Summary for loss and accuracy
    loss_summary = tf.summary.scalar('loss_summ', tf.reduce_max(self.loss, name='reduce_max_loss'))
    acc_summary = tf.summary.scalar('accuracy_summ', self.acc_op)

    grad_summaries = []
    for g, v in self.grads_and_vars:
      if g is not None:
        grad_hist_summary = tf.summary.histogram("{}/grad/hist".format(v.name), g)
        sparsity_summary = tf.summary.scalar("{}/grad/sparsity".format(v.name), tf.nn.zero_fraction(g))
        grad_summaries.append(grad_hist_summary)
        grad_summaries.append(sparsity_summary)
    self.grad_summaries_merged = tf.summary.merge(grad_summaries)

    # Train summaries
    self.train_summary_op = tf.summary.merge([loss_summary, acc_summary])
    train_summary_dir = os.path.join(out_dir, 'summaries', 'train')
    self.train_summary_writer = tf.summary.FileWriter(train_summary_dir, self.sess.graph)

    # Dev summaries
    self.dev_summary_op = tf.summary.merge([loss_summary, acc_summary])
    dev_summary_dir = os.path.join(out_dir, "summaries", "dev")
    self.dev_summary_writer = tf.summary.FileWriter(dev_summary_dir, self.sess.graph)

  def checkpoint(self, out_dir):
    """

    Args:
      out_dir:

    Returns:

    """
    checkpoint_dir = os.path.abspath(os.path.join(out_dir, 'checkpoints'))
    self.checkpoint_prefix = os.path.join(checkpoint_dir, 'model')

    if not os.path.exists(checkpoint_dir):
      os.mkdir(checkpoint_dir)
    self.saver = tf.train.Saver(tf.all_variables())
    path = self.saver.save(self.sess, self.checkpoint_prefix, global_step=self.global_step)
    print("Saved model checkpoint to {}\n".format(path))

  def train_step(self, inputs, sparse_targets, seq_len, check_value=False):
    """

    Args:
      inputs:
      sparse_targets:
      seq_len:
      check_value:

    Returns:

    """
    if check_value:
      X, y = self.sess.run([self.X, tf.sparse_tensor_to_dense(self.y, default_value=-1)])
      print(np.min(X[0]), np.mean(X[0]), np.max(X[0]))
      plt.imshow(X[1, :, :, 0])
      plt.title(' '.join(map(lambda x: str(x), y[1])))
      plt.show()
      return

    feed_dict = {
      self.X: inputs,
      self.y: sparse_targets,
      self.keep_prob: self.FLAGS.dropout_keep_prob,
      self.seq_len: seq_len
    }
    _, step, summaries, loss, accuracy = self.sess.run(
      [self.train_op, self.global_step,
       self.train_summary_op, self.cost, self.acc_op],
      feed_dict=feed_dict
    )

    # output, yy = self.sess.run([self.output, self.y], feed_dict=feed_dict)
    # time_str = datetime.datetime.now().isoformat()
    # print("{}:step{},loss:{},acc:{},decoded:{}".format(time_str, step, loss, accuracy, self.decoded[0]))
    # if self.interval_loss > loss:
    #   self.interval_loss = loss
    #   self.sess.run(tf.assign(self.global_step, tf.add(self.global_step, 1)))
    #   print("step:{}\tloss:{}\tacc:{}".format(step, loss, accuracy))
    print("step:{}\tloss:{}\tacc:{}".format(step, loss, accuracy))

    self.train_summary_writer.add_summary(summaries, step)
    if step % self.FLAGS.batch_size == 0:
      print('epoch:{}'.format(step // self.FLAGS.batch_size))

  def dev_step(self, inputs, sparse_targets, seq_len):
    """

    Args:
      inputs:
      sparse_targets:
      seq_len:

    Returns:

    """
    feed_dict = {
      self.X: inputs,
      self.y: sparse_targets,
      self.keep_prob: 1.,
      self.seq_len: seq_len
    }

    _, step, summaries, loss, accuracy = self.sess.run(
      [self.train_op, self.global_step,
       self.dev_summary_op, self.cost, self.acc_op
       ],
      feed_dict=feed_dict
    )

  def run(self):
    # inputs, sparse_targets, seq_len = get_next_batch(self.FLAGS.batch_size)
    for epoch in range(102400):
      # inputs, sparse_targets, seq_len = get_next_batch(self.FLAGS.batch_size)
      for step in range(32):
        inputs, sparse_targets, seq_len = get_next_batch(self.FLAGS.batch_size)
        # plot(inputs[0], str(step))
        self.train_step(inputs, sparse_targets, seq_len)
        current_step = tf.train.global_step(self.sess, self.global_step)
        if current_step % self.FLAGS.evaluate_every == 0:
          print("\nAfter epoch %s Evaluation:" % epoch)
          # inputs, sparse_targets, seq_len = get_next_batch(self.FLAGS.batch_size)
          self.dev_step(inputs, sparse_targets, seq_len)
          print('Evaluation Done\n')
          self._accuracy(inputs, sparse_targets, seq_len)
      # return
      # print("\nAfter epoch %s Evaluation:" % epoch)
      # # inputs, sparse_targets, seq_len = get_next_batch(self.FLAGS.batch_size)
      # self.dev_step(inputs, sparse_targets, seq_len)
      # print('Evaluation Done\n')
      # self._accuracy()


if __name__ == '__main__':
  tmp_path = '../../run_temp/'
  rmeds = os.listdir(tmp_path)
  for rmed in rmeds:
    joint = os.path.join(tmp_path, rmed)
    try:
      os.rmdir(joint)
    except Exception as e:
      try:
        os.remove(joint)
      except Exception as e:
        shutil.rmtree(joint)
    print('Removed {} done.'.format(os.path.join(tmp_path, rmed)))

  tf.app.flags.DEFINE_boolean("allow_soft_placement",
                              True, "Allow device soft device placement")
  tf.app.flags.DEFINE_boolean("log_device_placement",
                              False, "Log placement of ops on devices")
  tf.app.flags.DEFINE_integer("batch_size",
                              32, "Batch Size (default: 64)")
  tf.app.flags.DEFINE_float("dropout_keep_prob",
                            1., "Dropout keep probability")
  tf.app.flags.DEFINE_integer("evaluate_every",
                              100, "Evaluate model on dev set after this many steps (default: 100)")
  tf.app.flags.DEFINE_integer('rnn_units',
                              128, "Rnn Units")
  # 初始化学习速率
  tf.app.flags.DEFINE_float('INITIAL_LEARNING_RATE', 1e-4, 'Learning rate initial value')
  tf.app.flags.DEFINE_integer('DECAY_STEPS', 10000, 'DECAY_STEPS')
  tf.app.flags.DEFINE_integer('REPORT_STEPS', 100, 'REPORT_STEPS')
  tf.app.flags.DEFINE_float('LEARNING_RATE_DECAY_FACTOR', 0.0, 'LEARNING_RATE_DECAY_FACTOR')

  crnn = CRNN(n_class, input_shape=[None, width, height, 1])
  crnn.architecture()
  crnn.run()
  # print('Build model done!')
  print('Training done!')
